"""Risk-based routing: low risk auto-approved by policy (0-30), medium -> Manager only (31-60), high -> Manager + Security Manager."""
import pytest
from sqlalchemy import select

from app.models import AccessGrant, AuditEvent, Notification, Policy, Resource
from app.services.workflow import ROUTING_POLICY_NAME
from tests.conftest import login, set_routing, user_by_email


def rid(db, code):
    return db.execute(select(Resource.id).where(Resource.code == code)).scalar_one()


def submit(client, h, code, db, perms, purpose, hours, why="Quarterly reporting pack for the leadership review meeting."):
    r = client.post("/api/requests", headers=h, json={"resource_id": rid(db, code), "permissions": perms, "purpose": purpose,
                                                      "justification": why, "duration_hours": hours})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def routing_on():
    set_routing(True)
    yield
    set_routing(False)


def test_low_risk_is_auto_approved_by_policy_and_manager_is_informed(client, db, routing_on):
    neha = login(client, "neha.gupta")
    req = submit(client, neha, "RES-ENG-001", db, ["READ"], "ANALYTICS_REPORTING", 8)
    assert req["risk"]["score"] <= 30
    assert req["status"] == "APPROVED" and req["required_stages"] == [] and req["current_stage"] is None
    g = db.execute(select(AccessGrant).where(AccessGrant.request_id == req["id"])).scalar_one()
    assert g.status == "ACTIVE" and g.permissions == ["READ"]
    ev = db.execute(select(AuditEvent).where(AuditEvent.request_id == req["id"],
                                             AuditEvent.action == "REQUEST_AUTO_APPROVED")).scalar_one()
    assert ev.actor_type == "SYSTEM" and ev.actor_name == "ASTITVA Policy Engine" and "Auto-approved by policy" in ev.reason
    assert f"{req['risk']['score']}" in ev.reason and "None" not in ev.reason
    priya = user_by_email(db, "priya.desai")
    n = db.execute(select(Notification).where(Notification.user_id == priya.id, Notification.kind == "REQUEST_AUTO_APPROVED")
                   .order_by(Notification.created_at.desc())).scalars().first()
    assert n and "Neha Gupta" in n.title and "READ" in n.body
    assert f"risk {req['risk']['score']}/100" in n.body
    # Nobody has anything to approve
    assert all(i["id"] != req["id"] for i in client.get("/api/approvals/queue", headers=login(client, "priya.desai")).json()["actionable"])


def test_medium_risk_needs_manager_only(client, db, routing_on):
    kavya = login(client, "kavya.reddy")
    req = submit(client, kavya, "RES-DS-003", db, ["READ", "WRITE"], "MODEL_TRAINING", 168)
    assert 30 < req["risk"]["score"] <= 60, req["risk"]
    assert req["required_stages"] == ["MANAGER"]
    r = client.post(f"/api/approvals/{req['id']}/action", headers=login(client, "priya.desai"), json={"action": "APPROVE"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert db.execute(select(AccessGrant).where(AccessGrant.request_id == req["id"])).scalar_one().status == "ACTIVE"


def test_high_risk_needs_manager_and_security_manager(client, db, routing_on):
    rahul = login(client, "rahul.sharma")
    req = submit(client, rahul, "RES-DS-001", db, ["READ", "EXECUTE", "WRITE"], "FRONTEND_TESTING", 72, "ui testing only")
    assert req["risk"]["score"] > 60
    assert req["required_stages"] == ["MANAGER", "RISK"]
    r = client.post(f"/api/approvals/{req['id']}/action", headers=login(client, "priya.desai"), json={"action": "APPROVE"})
    assert r.json()["status"] == "PENDING" and r.json()["current_stage"] == "RISK"
    r = client.post(f"/api/approvals/{req['id']}/action", headers=login(client, "admin"), json={"action": "REJECT",
                                                                                             "comment": "Purpose mismatch"})
    assert r.json()["status"] == "REJECTED"


def test_critical_resources_are_never_auto_approved(client, db, routing_on):
    # Even a low score on a CRITICAL resource goes to a human (excluded sensitivity)
    set_routing(True, auto=100, manager_only=100)
    kavya = login(client, "kavya.reddy")
    req = submit(client, kavya, "RES-DS-001", db, ["READ"], "MODEL_TESTING", 8)
    assert req["status"] == "PENDING" and req["required_stages"] == ["MANAGER"]


def test_thresholds_are_admin_configurable_and_validated(client, db, routing_on):
    admin = login(client, "admin")
    pol = next(p for p in client.get("/api/policies", headers=admin).json()["policies"] if p["name"] == ROUTING_POLICY_NAME)
    body = {"name": pol["name"], "policy_type": "GLOBAL", "description": pol["description"], "resource_id": None,
            "enabled": True, "rules": {**pol["rules"], "auto_approve_max_score": 80, "manager_only_max_score": 50}}
    assert client.put(f"/api/policies/{pol['id']}", headers=admin, json=body).status_code == 422  # auto > manager
    body["rules"].update(auto_approve_max_score=20, manager_only_max_score=60)
    assert client.put(f"/api/policies/{pol['id']}", headers=admin, json=body).status_code == 200
    db.expire_all()
    assert db.get(Policy, pol["id"]).rules["auto_approve_max_score"] == 20
    # Managers cannot change routing
    assert client.put(f"/api/policies/{pol['id']}", headers=login(client, "priya.desai"), json=body).status_code == 403
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "POLICY_UPDATED", AuditEvent.target_id == pol["id"])).scalars().first()
