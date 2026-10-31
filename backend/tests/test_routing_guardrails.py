"""Guardrails: sensitive resources, WRITE/DELETE/ADMIN and anomalies always need a human, whatever the score."""
import pytest
from sqlalchemy import select

from app.models import Policy, Resource
from app.services.workflow import ROUTING_POLICY_NAME, route
from tests.conftest import login, set_routing, user_by_email


@pytest.fixture
def routing_on():
    set_routing(True)
    yield
    set_routing(False)


def res(db, code):
    return db.execute(select(Resource).where(Resource.code == code)).scalar_one()


def test_score_bands_on_a_non_sensitive_read(db, routing_on):
    r, emp = res(db, "RES-ENG-001"), user_by_email(db, "rahul.sharma")
    assert r.sensitivity == "INTERNAL"
    assert route(r, 0, emp, db, ["READ"])[0] == []
    assert route(r, 30, emp, db, ["READ"])[0] == []
    assert route(r, 31, emp, db, ["READ"])[0] == ["MANAGER"]
    assert route(r, 60, emp, db, ["READ"])[0] == ["MANAGER"]
    assert route(r, 61, emp, db, ["READ"])[0] == ["MANAGER", "RISK"]
    assert route(r, 100, emp, db, ["READ"])[0] == ["MANAGER", "RISK"]


@pytest.mark.parametrize("code", ["RES-DS-002", "RES-HR-001", "RES-DS-001"])  # CONFIDENTIAL, RESTRICTED, CRITICAL
def test_sensitive_resources_are_never_auto_approved(db, routing_on, code):
    stages, reasons = route(res(db, code), 0, user_by_email(db, "rahul.sharma"), db, ["READ"])
    assert stages == ["MANAGER"]
    assert any("never approved automatically" in x for x in reasons)


@pytest.mark.parametrize("perm", ["WRITE", "DELETE", "ADMIN"])
def test_write_delete_admin_are_never_auto_approved(db, routing_on, perm):
    stages, reasons = route(res(db, "RES-ENG-002"), 5, user_by_email(db, "rahul.sharma"), db, ["READ", perm])
    assert stages == ["MANAGER"] and any(perm in x for x in reasons)


def test_execute_alone_can_be_auto_approved(db, routing_on):
    assert route(res(db, "RES-ENG-001"), 10, user_by_email(db, "rahul.sharma"), db, ["READ", "EXECUTE"])[0] == []


def test_anomaly_forces_security_review_even_at_low_score(db, routing_on):
    stages, reasons = route(res(db, "RES-ENG-001"), 5, user_by_email(db, "rahul.sharma"), db, ["READ"], anomalous=True)
    assert stages == ["MANAGER", "RISK"] and "Unusual behaviour" in reasons[0]


def test_guardrails_hold_even_if_policy_is_loosened_in_the_database(db, routing_on):
    p = db.execute(select(Policy).where(Policy.name == ROUTING_POLICY_NAME)).scalar_one()
    p.rules = {**p.rules, "auto_approve_max_score": 100, "manager_only_max_score": 100,
               "auto_approve_excluded_sensitivities": [], "auto_approve_allowed_permissions": ["READ", "WRITE", "ADMIN"]}
    db.commit()
    emp = user_by_email(db, "rahul.sharma")
    assert route(res(db, "RES-FIN-003"), 1, emp, db, ["READ"])[0] == ["MANAGER"]       # CRITICAL
    assert route(res(db, "RES-ENG-002"), 1, emp, db, ["WRITE"])[0] == ["MANAGER"]      # WRITE


def test_admin_cannot_remove_guardrails_through_the_api(client, db, routing_on):
    admin = login(client, "admin")
    pol = next(p for p in client.get("/api/policies", headers=admin).json()["policies"] if p["name"] == ROUTING_POLICY_NAME)
    body = {"name": pol["name"], "policy_type": "GLOBAL", "description": pol["description"], "resource_id": None,
            "enabled": True, "rules": {**pol["rules"], "auto_approve_allowed_permissions": ["READ", "WRITE"]}}
    assert client.put(f"/api/policies/{pol['id']}", headers=admin, json=body).status_code == 422
    body["rules"].update(auto_approve_allowed_permissions=["READ"], auto_approve_excluded_sensitivities=[])
    assert client.put(f"/api/policies/{pol['id']}", headers=admin, json=body).status_code == 200
    db.expire_all()
    saved = db.get(Policy, pol["id"]).rules
    assert {"CONFIDENTIAL", "RESTRICTED", "CRITICAL"} <= set(saved["auto_approve_excluded_sensitivities"])
    assert saved["anomaly_requires_security_review"] is True


def test_request_carries_the_reason_for_its_approval_path(client, db, routing_on):
    rahul = login(client, "rahul.sharma")
    r = client.post("/api/requests", headers=rahul, json={
        "resource_id": res(db, "RES-DS-002").id, "permissions": ["READ"], "purpose": "MODEL_TESTING",
        "justification": "Compare recommendation quality before and after the Atlas checkout change.", "duration_hours": 8})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING" and body["required_stages"]
    assert any("CONFIDENTIAL" in x for x in body["routing_reasons"])
