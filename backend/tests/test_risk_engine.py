"""Risk engine correctness: what counts as a violation, time bounds, velocity, group caps and the anomaly model.
Each test works inside a transaction that is rolled back, so the shared demo data is not changed."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.catalog import risk_level
from app.core.risk_config import WEIGHTS
from app.models import AccessGrant, AccessRequest, Resource, ResourceAccessEvent, SecurityAlert, User, utcnow
from app.security import crypto
from app.services import risk

NOW = utcnow()
_n = [0]


@pytest.fixture
def tx(db):
    yield db
    db.rollback()


def res(db, code="RES-ENG-001"):
    return db.execute(select(Resource).where(Resource.code == code)).scalar_one()


def person(db) -> User:
    _n[0] += 1
    u = User(employee_id=f"TST{_n[0]:05d}", email=f"risk.test{_n[0]}@example.test", full_name=f"Risk Test {_n[0]}",
             password_hash=crypto.hash_password("not-used-Passw0rd!"))
    db.add(u)
    db.flush()
    return u


def request(db, u, created, status="PENDING", code="RES-ENG-001", perms=("READ",),
            why="Pull checkout conversion metrics for the sprint review deck.") -> AccessRequest:
    r = AccessRequest(ref=f"T-{uuid.uuid4().hex[:20]}", requester_id=u.id,
                      resource_id=res(db, code).id, requested_permissions=list(perms), approved_permissions=list(perms),
                      purpose="ANALYTICS_REPORTING", justification=why, requested_duration_hours=8,
                      approved_duration_hours=8, status=status, required_stages=[], created_at=created)
    db.add(r)
    db.flush()
    return r


def alert(db, u, created, status="OPEN", resolution=None, category="UNAUTHORIZED_ACCESS"):
    db.add(SecurityAlert(severity="MEDIUM", category=category, title="t", description="d", user_id=u.id,
                         status=status, resolution=resolution, created_at=created))
    db.flush()


def codes(ra):
    return {f["code"]: f for f in ra.factors}


def test_rejected_requests_are_not_violations(tx):
    u = person(tx)
    for d in (3, 6, 9, 12):
        request(tx, u, NOW - timedelta(days=d), status="REJECTED")
    ra = risk.assess(tx, request(tx, u, NOW))
    assert not {"CONFIRMED_VIOLATIONS", "UNREVIEWED_ALERTS", "REPEATED_DENIALS"} & set(codes(ra))


def test_confirmed_alerts_count_more_than_unreviewed_and_false_positives_not_at_all(tx):
    u = person(tx)
    alert(tx, u, NOW - timedelta(days=5), "RESOLVED", "CONFIRMED")
    alert(tx, u, NOW - timedelta(days=4), "OPEN")
    alert(tx, u, NOW - timedelta(days=3), "RESOLVED", "FALSE_POSITIVE")
    f = codes(risk.assess(tx, request(tx, u, NOW)))
    assert f["CONFIRMED_VIOLATIONS"]["points"] == WEIGHTS["CONFIRMED_VIOLATION_EACH"]
    assert "1 violation" in f["CONFIRMED_VIOLATIONS"]["detail"]
    assert f["UNREVIEWED_ALERTS"]["points"] == WEIGHTS["OPEN_ALERT_EACH"]
    assert f["UNREVIEWED_ALERTS"]["points"] < f["CONFIRMED_VIOLATIONS"]["points"]


@pytest.mark.parametrize("n,expected", [(2, None), (3, WEIGHTS["REPEATED_DENIALS"]), (10, WEIGHTS["REPEATED_DENIALS_HIGH"])])
def test_denied_operations_are_a_separate_weak_signal(tx, n, expected):
    u = person(tx)
    for i in range(n):
        tx.add(ResourceAccessEvent(user_id=u.id, resource_id=res(tx).id, action="READ", outcome="DENIED",
                                   occurred_at=NOW - timedelta(days=1, minutes=i)))
    tx.flush()
    f = codes(risk.assess(tx, request(tx, u, NOW)))
    assert f.get("REPEATED_DENIALS", {}).get("points") == expected
    assert "CONFIRMED_VIOLATIONS" not in f


def test_events_after_the_request_are_never_used(tx):
    u = person(tx)
    made = NOW - timedelta(days=10)
    req = request(tx, u, made)
    alert(tx, u, made + timedelta(days=2), "RESOLVED", "CONFIRMED")         # happened after the request
    tx.add(AccessGrant(user_id=u.id, resource_id=res(tx).id, permissions=["READ"], purpose="ANALYTICS_REPORTING",
                       source="REQUEST", granted_at=made + timedelta(days=1), expires_at=made + timedelta(days=2),
                       status="EXPIRED"))
    for d in range(6):
        request(tx, u, made + timedelta(hours=d + 1))                            # later requests
    tx.flush()
    f = codes(risk.assess(tx, req))
    assert "CONFIRMED_VIOLATIONS" not in f and "REQUEST_VELOCITY" not in f
    assert "FIRST_ACCESS" in f and "PRIOR_ACCESS" not in f


def test_velocity_excludes_the_current_request(tx):
    u = person(tx)
    for d in range(4):
        request(tx, u, NOW - timedelta(days=d + 1))
    assert "REQUEST_VELOCITY" not in codes(risk.assess(tx, request(tx, u, NOW)))   # 4 others + this one
    u2 = person(tx)
    for d in range(5):
        request(tx, u2, NOW - timedelta(days=d + 1))
    f = codes(risk.assess(tx, request(tx, u2, NOW)))
    assert f["REQUEST_VELOCITY"]["points"] == WEIGHTS["VELOCITY"] and "5 other requests" in f["REQUEST_VELOCITY"]["detail"]


def test_velocity_compares_with_the_persons_own_baseline(tx):
    u = person(tx)
    for w in range(8):                       # 5 requests every week for 8 weeks before the window = normal pace
        for i in range(5):
            request(tx, u, NOW - timedelta(days=8 + 7 * w, hours=i))
    for d in range(5):
        request(tx, u, NOW - timedelta(days=d + 1))
    assert "REQUEST_VELOCITY" not in codes(risk.assess(tx, request(tx, u, NOW)))


def test_related_history_signals_share_one_cap(tx):
    u = person(tx)
    for d in range(4):
        alert(tx, u, NOW - timedelta(days=d + 1), "RESOLVED", "CONFIRMED")
    for d in range(3):
        alert(tx, u, NOW - timedelta(days=d + 1), "OPEN")
    ra = risk.assess(tx, request(tx, u, NOW))
    assert sum(f["points"] for f in ra.factors if f.get("group") == "HISTORY") == WEIGHTS["HISTORY_GROUP_MAX"]


def test_anomaly_model_reports_insufficient_data_instead_of_guessing(tx):
    u = person(tx)
    ra = risk.assess(tx, request(tx, u, NOW))
    f = codes(ra)["BEHAVIOUR_MODEL"]
    assert f["available"] is False and f["points"] == 0 and "Not enough data" in f["detail"]
    assert ra.engine.startswith("rules-v2") and "isolation-forest" not in ra.engine
    assert "Not used (insufficient data)" in ra.explanation


def test_anomaly_model_with_enough_people_is_reproducible_and_cached(tx):
    day = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    codes_ = ["RES-ENG-001", "RES-ENG-002", "RES-DS-002", "RES-DS-003", "RES-FIN-001", "RES-FIN-002", "RES-HR-001",
              "RES-DS-001", "RES-FIN-003"]
    normal = []
    for i in range(14):
        u = person(tx)
        normal.append(u)
        for k in range(2):
            request(tx, u, day - timedelta(days=3 + i % 5 + k, hours=-11))   # working hours, one resource
    odd = person(tx)
    for k in range(27):
        request(tx, odd, day - timedelta(days=1 + k % 20, hours=2), code=codes_[k % len(codes_)])  # 22:00, many resources
    first = risk.anomaly_signal(tx, odd.id, NOW)
    again = risk.anomaly_signal(tx, odd.id, NOW)
    assert first.status == "ANOMALOUS" and first.population >= 12 and "outlier" in first.detail
    assert first.score == again.score                                  # same data -> same result (fixed seed)
    assert risk.anomaly_signal(tx, normal[0].id, NOW).status == "NORMAL"
    assert len(risk._MODEL_CACHE) >= 1


def test_weights_come_from_the_central_config(tx, monkeypatch):
    monkeypatch.setitem(WEIGHTS, "WEAK_JUSTIFICATION", 30)
    u = person(tx)
    f = codes(risk.assess(tx, request(tx, u, NOW, why="need it")))
    assert f["WEAK_JUSTIFICATION"]["points"] == 30


def test_score_is_bounded_and_level_matches_the_shared_scale(tx):
    u = person(tx)
    u.device_trust = "UNTRUSTED"
    ra = risk.assess(tx, request(tx, u, NOW, code="RES-FIN-003", perms=("READ", "WRITE", "DELETE", "ADMIN"), why="x"))
    assert 0 <= ra.score <= 100 and ra.level == risk_level(ra.score)
    assert (risk_level(30), risk_level(31), risk_level(60), risk_level(61), risk_level(80), risk_level(81)) == \
        ("LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL")
