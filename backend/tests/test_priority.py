"""Deadline-based priority: bands, formula, levels, validation, queue ordering, and independence from risk."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import AccessRequest, AuditEvent, Resource
from app.services import priority
from app.services.priority import compute, deadline_points, level, waiting_points
from app.services.workflow import WorkflowError, validate_priority_inputs
from tests.conftest import login

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)   # fixed clock
H = lambda h: timedelta(hours=h)  # noqa: E731


@pytest.mark.parametrize("hours,pts", [(0, 0), (3.99, 0), (4, 20), (23.9, 20), (24, 40), (71.9, 40), (72, 70),
                                       (168, 70), (168.1, 100), (400, 100)])
def test_waiting_time_bands(hours, pts):
    assert waiting_points(H(hours)) == pts


@pytest.mark.parametrize("hours,pts", [(None, 0), (200, 0), (168.1, 0), (168, 10), (72.1, 10), (72, 25), (24.1, 25),
                                       (24, 40), (6.1, 40), (6, 50), (0.5, 50), (0, 60), (-5, 60)])
def test_deadline_bands(hours, pts):
    assert deadline_points(None if hours is None else H(hours)) == pts


def test_business_impact_mapping():
    assert priority.IMPACT_SCORE == {"LOW": 10, "MEDIUM": 40, "HIGH": 70, "CRITICAL": 100}


@pytest.mark.parametrize("score,lvl", [(0, "LOW"), (24, "LOW"), (25, "MEDIUM"), (49, "MEDIUM"), (50, "HIGH"),
                                       (74, "HIGH"), (75, "CRITICAL"), (100, "CRITICAL")])
def test_levels(score, lvl):
    assert level(score) == lvl


def test_formula_worked_example():
    # deadline in 2h (50), CRITICAL (100), waiting 30h (40), incident response (100)
    p = compute(created_at=T0 - H(30), deadline_at=T0 + H(2), business_impact="CRITICAL", purpose="INCIDENT_RESPONSE", now=T0)
    assert p.components == {"deadline": 50, "impact": 100, "waiting": 40, "urgency": 100}
    assert p.score == round(0.4 * 50 + 0.3 * 100 + 0.2 * 40 + 0.1 * 100) == 68 and p.level == "HIGH"
    assert p.approaching and not p.overdue
    assert any("Deadline in 2 h" in r for r in p.reasons) and any("urgent purpose" in r for r in p.reasons)


def test_minimum_and_maximum_stay_in_range():
    lo = compute(created_at=T0, deadline_at=None, business_impact="LOW", purpose="ANALYTICS_REPORTING", now=T0)
    hi = compute(created_at=T0 - H(500), deadline_at=T0 - H(1), business_impact="CRITICAL", purpose="INCIDENT_RESPONSE", now=T0)
    assert lo.score == 3 and lo.level == "LOW" and "No deadline given (+0)." in lo.reasons
    assert 0 <= hi.score <= 100 and hi.level == "CRITICAL" and hi.overdue and not hi.approaching


def test_priority_rises_as_time_passes_with_the_same_inputs():
    args = dict(created_at=T0, deadline_at=T0 + H(100), business_impact="MEDIUM", purpose="MODEL_TESTING")
    scores = [compute(**args, now=T0 + H(h)).score for h in (0, 30, 80, 99, 101)]
    assert scores == sorted(scores) and scores[-1] > scores[0]
    assert compute(**args, now=T0 + H(101)).overdue


def test_naive_datetimes_are_treated_as_utc():
    a = compute(created_at=T0.replace(tzinfo=None), deadline_at=(T0 + H(5)).replace(tzinfo=None),
                business_impact="HIGH", purpose="MODEL_TESTING", now=T0)
    b = compute(created_at=T0, deadline_at=T0 + H(5), business_impact="HIGH", purpose="MODEL_TESTING", now=T0)
    assert a == b


def test_deadline_validation():
    with pytest.raises(WorkflowError, match="past"):
        validate_priority_inputs(T0 - H(1), "LOW", now=T0)
    with pytest.raises(WorkflowError, match="timezone"):
        validate_priority_inputs(datetime(2026, 11, 3, 9, 0), "LOW", now=T0)
    with pytest.raises(WorkflowError, match="Business impact"):
        validate_priority_inputs(None, "URGENT", now=T0)
    ist = timezone(timedelta(hours=5, minutes=30))
    d, imp = validate_priority_inputs(datetime(2026, 11, 3, 18, 0, tzinfo=ist), "high", now=T0)
    assert d == datetime(2026, 11, 3, 12, 30, tzinfo=timezone.utc) and imp == "HIGH"


# ------------------------------------------------------------------ API
def rid(db, code):
    return db.execute(select(Resource.id).where(Resource.code == code)).scalar_one()


def clear_open(client, h, db, code):
    for r in client.get("/api/requests", headers=h).json():
        if r["resource"]["code"] == code and r["status"] in ("PENDING", "CHANGES_REQUESTED"):
            client.post(f"/api/requests/{r['id']}/cancel", headers=h)


def body(db, code, **kw):
    return {"resource_id": rid(db, code), "permissions": ["READ"], "purpose": "COMPLIANCE_AUDIT",
            "justification": "Quarterly access evidence for the internal audit sample set.", "duration_hours": 8, **kw}


def test_api_rejects_past_deadline_and_ignores_a_client_supplied_score(client, db):
    neha = login(client, "neha.gupta")
    clear_open(client, neha, db, "RES-FIN-003")
    past = (datetime.now(timezone.utc) - H(2)).isoformat()
    r = client.post("/api/requests", headers=neha, json=body(db, "RES-FIN-003", deadline_at=past))
    assert r.status_code == 422 and "past" in r.text
    soon = (datetime.now(timezone.utc) + H(5)).isoformat()
    r = client.post("/api/requests", headers=neha, json=body(db, "RES-FIN-003", deadline_at=soon, business_impact="HIGH",
                                                             priority={"score": 100, "level": "CRITICAL"}))
    assert r.status_code == 201, r.text
    p = r.json()["priority"]
    assert p["components"]["deadline"] == 50 and p["components"]["impact"] == 70 and p["score"] < 100
    assert p["approaching"] and r.json()["business_impact"] == "HIGH"


def test_requester_can_change_deadline_and_impact_while_open_and_it_is_audited(client, db):
    kavya = login(client, "kavya.reddy")
    mine = client.get("/api/requests", headers=kavya).json()
    req = next(r for r in mine if r["status"] == "PENDING")
    new = (datetime.now(timezone.utc) + H(48)).isoformat()
    r = client.patch(f"/api/requests/{req['id']}/priority-inputs", headers=kavya,
                     json={"deadline_at": new, "business_impact": "CRITICAL"})
    assert r.status_code == 200, r.text
    assert r.json()["business_impact"] == "CRITICAL" and r.json()["priority"]["components"]["deadline"] == 25
    assert db.execute(select(AuditEvent).where(AuditEvent.request_id == req["id"],
                                               AuditEvent.action == "REQUEST_PRIORITY_INPUTS_CHANGED")).scalars().first()
    # someone else cannot
    r = client.patch(f"/api/requests/{req['id']}/priority-inputs", headers=login(client, "rahul.sharma"),
                     json={"deadline_at": None, "business_impact": "LOW"})
    assert r.status_code == 404


def test_priority_does_not_change_risk_or_approval_path(client, db):
    rahul = login(client, "rahul.sharma")
    clear_open(client, rahul, db, "RES-FIN-001")
    a = client.post("/api/requests", headers=rahul, json=body(db, "RES-FIN-001", purpose="ANALYTICS_REPORTING",
                                                              business_impact="LOW")).json()
    soon = (datetime.now(timezone.utc) + H(2)).isoformat()
    b = client.patch(f"/api/requests/{a['id']}/priority-inputs", headers=rahul,
                     json={"deadline_at": soon, "business_impact": "CRITICAL"}).json()
    assert b["priority"]["score"] > a["priority"]["score"]
    assert a["risk"]["score"] == b["risk"]["score"] and a["required_stages"] == b["required_stages"]
    # and the risk engine itself ignores the priority inputs
    from app.services import risk
    req = db.get(AccessRequest, a["id"])
    s1 = risk.assess(db, req).score
    req.business_impact, req.deadline_at = "LOW", None
    s2 = risk.assess(db, req).score
    db.rollback()
    assert s1 == s2


def test_queue_sorts_and_filters(client, db):
    admin = login(client, "admin")
    q = client.get("/api/approvals/queue?sort=priority", headers=admin).json()
    items = q["actionable"] + q["watching"]
    for lst in (q["actionable"], q["watching"]):
        scores = [i["priority"]["score"] for i in lst]
        assert scores == sorted(scores, reverse=True)
    assert any(i["priority"]["overdue"] for i in items)          # the seeded overdue request
    over = client.get("/api/approvals/queue?filter=overdue", headers=admin).json()
    assert over["actionable"] + over["watching"] and all(i["priority"]["overdue"] for i in over["actionable"] + over["watching"])
    wait = client.get("/api/approvals/queue?sort=waiting", headers=admin).json()["watching"]
    assert [i["created_at"] for i in wait] == sorted(i["created_at"] for i in wait)
    assert client.get("/api/approvals/queue?filter=URGENT", headers=admin).status_code == 422


def test_closed_requests_have_no_priority(client, db):
    rows = db.execute(select(AccessRequest).where(AccessRequest.status == "APPROVED").limit(1)).scalars().all()
    from app.api.serializers import request_out
    assert rows and request_out(rows[0])["priority"] is None
