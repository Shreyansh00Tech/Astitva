"""Additional security and workflow tests beyond the 15 acceptance scenarios."""
from sqlalchemy import select

from app.models import AccessRequest, Resource, SecurityAlert, UserSession
from app.seed import DEMO_PASSWORD
from tests.conftest import email, latest_otp, login, user_by_email


def rid(db, code):
    return db.execute(select(Resource.id).where(Resource.code == code)).scalar_one()


def test_cookie_session_requires_csrf_and_refresh_rotation_detects_reuse(client, db):
    r = client.post("/api/auth/login", json={"email": email("priya.desai"), "password": DEMO_PASSWORD})
    mt = r.json()["mfa_token"]
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": mt, "method": "EMAIL", "code": latest_otp(email("priya.desai"))})
    assert r.status_code == 200
    set_cookie = ",".join(r.headers.get_list("set-cookie"))
    assert "HttpOnly" in set_cookie and "SameSite=strict" in set_cookie
    assert client.get("/api/auth/me").status_code == 200  # cookie auth works for reads
    # State change without the CSRF header is refused
    assert client.post("/api/notifications/read-all").status_code == 403
    csrf = client.cookies.get("astitva_csrf")
    assert client.post("/api/notifications/read-all", headers={"X-CSRF-Token": csrf}).status_code == 200
    # Refresh rotation + reuse detection
    old_rt = client.cookies.get("astitva_rt")
    r = client.post("/api/auth/refresh", json={"refresh_token": old_rt})
    assert r.status_code == 200 and r.json()["refresh_token"] != old_rt
    r = client.post("/api/auth/refresh", json={"refresh_token": old_rt})
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_REUSED"
    assert db.execute(select(SecurityAlert).where(SecurityAlert.category == "TOKEN_REUSE")).scalars().first()
    client.cookies.clear()


def test_logout_invalidates_session(client, db):
    h = login(client, "priya.desai")
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_risk_engine_flags_purpose_mismatch_and_recommends_least_privilege(client, db):
    """Spec example: WRITE on a confidential financial dataset for frontend testing."""
    req = db.execute(select(AccessRequest).join(Resource).where(Resource.code == "RES-FIN-002",
                                                                 AccessRequest.purpose == "FRONTEND_TESTING",
                                                                 AccessRequest.requester_id == user_by_email(db, "rahul.sharma").id)).scalars().first()
    risk = req.risk
    codes = {f["code"] for f in risk.factors}
    assert {"PURPOSE_MISMATCH", "EXCESSIVE_PERMISSIONS", "SENSITIVITY", "LONG_DURATION"} <= codes
    assert risk.level in ("HIGH", "CRITICAL")
    assert risk.recommended_permissions == ["READ"] and risk.recommended_duration_hours <= 24
    assert "advisory" in risk.explanation.lower()


def test_narrow_scope_and_request_modification(client, db):
    rahul = login(client, "rahul.sharma")
    priya = login(client, "priya.desai")
    r = client.post("/api/requests", headers=rahul, json={"resource_id": rid(db, "RES-ENG-001"), "permissions": ["READ", "WRITE"],
                                                          "purpose": "ANALYTICS_REPORTING", "duration_hours": 200,
                                                          "justification": "Build the weekly reliability dashboard for SRE review."})
    req = r.json()
    # Narrowing cannot widen scope
    bad = client.post(f"/api/approvals/{req['id']}/action", headers=priya,
                      json={"action": "NARROW_SCOPE", "permissions": ["READ", "WRITE", "EXECUTE"]})
    assert bad.status_code == 422
    ok = client.post(f"/api/approvals/{req['id']}/action", headers=priya,
                     json={"action": "NARROW_SCOPE", "permissions": ["READ"], "duration_hours": 24, "comment": "Read is enough"})
    assert ok.status_code == 200 and ok.json()["approved_permissions"] == ["READ"] and ok.json()["approved_duration_hours"] == 24
    assert ok.json()["current_stage"] == "RISK"
    reviewer = login(client, "admin")  # Security Manager
    r = client.post(f"/api/approvals/{req['id']}/action", headers=reviewer, json={"action": "REQUEST_MODIFICATION"})
    assert r.status_code == 422  # comment required
    r = client.post(f"/api/approvals/{req['id']}/action", headers=reviewer,
                    json={"action": "REQUEST_MODIFICATION", "comment": "Name the dashboard ticket"})
    assert r.status_code == 200 and r.json()["status"] == "CHANGES_REQUESTED"
    r = client.post(f"/api/requests/{req['id']}/resubmit", headers=rahul, json={
        "permissions": ["READ"], "purpose": "ANALYTICS_REPORTING", "duration_hours": 24,
        "justification": "Build the weekly reliability dashboard for SRE review (ticket HEL-221)."})
    assert r.status_code == 200 and r.json()["status"] == "PENDING" and r.json()["current_stage"] == "MANAGER"


def test_role_based_route_protection(client):
    manager = login(client, "priya.desai")
    me = client.get("/api/auth/me", headers=manager).json()
    assert "MANAGER" in me["roles"] and "approvals:act" in me["permissions"]
    # The Manager handles approvals, not security administration
    assert client.get("/api/audit/events", headers=manager).status_code == 403
    assert client.post("/api/policies", headers=manager, json={"name": "x" * 5, "policy_type": "SOD",
                                                               "rules": {"kind": "STAGE_CONFLICT"}}).status_code == 403
    assert client.get("/api/admin/users", headers=manager).status_code == 403
    assert client.post("/api/drift/scan", headers=manager).status_code == 403
    # The Security Manager does
    sec = login(client, "admin")
    assert client.get("/api/audit/events", headers=sec).status_code == 200
    assert client.get("/api/admin/users", headers=sec).status_code == 200
    roles = client.get("/api/auth/me", headers=sec).json()["roles"]
    assert {"SECURITY_ADMIN", "RISK_REVIEWER"} <= set(roles)


def test_registration_verification_and_password_policy(client, db):
    weak = client.post("/api/auth/register", json={"email": email("new.joiner"), "full_name": "New Joiner", "password": "password123"})
    assert weak.status_code == 422
    r = client.post("/api/auth/register", json={"email": email("new.joiner"), "full_name": "New Joiner",
                                                "password": "Tr1cky-Horse-Battery!"})
    assert r.status_code == 202
    # unverified users cannot sign in
    assert client.post("/api/auth/login", json={"email": email("new.joiner"), "password": "Tr1cky-Horse-Battery!"}).status_code == 403
    code = latest_otp(email("new.joiner"))
    assert client.post("/api/auth/verify-email", json={"email": email("new.joiner"), "code": code}).status_code == 200
    h = login(client, "new.joiner", "Tr1cky-Horse-Battery!")
    assert client.get("/api/auth/me", headers=h).json()["roles"] == ["REQUESTER"]
    # duplicate registration does not reveal existence
    again = client.post("/api/auth/register", json={"email": email("new.joiner"), "full_name": "X Y", "password": "Tr1cky-Horse-Battery!"})
    assert again.status_code == 202


def test_password_reset_revokes_sessions(client, db):
    # use a freshly registered account so the demo users keep their demo password
    client.post("/api/auth/register", json={"email": email("reset.tester"), "full_name": "Reset Tester",
                                            "password": "Tr1cky-Horse-Battery!"})
    assert client.post("/api/auth/verify-email", json={"email": email("reset.tester"),
                                                       "code": latest_otp(email("reset.tester"))}).status_code == 200
    h = login(client, "reset.tester", "Tr1cky-Horse-Battery!")
    client.post("/api/auth/forgot-password", json={"email": email("reset.tester")})
    from app.models import DevOutbox
    import re

    body = db.execute(select(DevOutbox).where(DevOutbox.recipient == email("reset.tester")).order_by(DevOutbox.id.desc())).scalars().first().body
    token = re.search(r"token=(\S+)", body).group(1)
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "weak"}).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "Fresh-Orchid-Lantern-9"}).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "Another-Orchid-77!"}).status_code == 400
    h2 = login(client, "reset.tester", "Fresh-Orchid-Lantern-9")
    assert client.get("/api/auth/me", headers=h2).status_code == 200


def test_dashboard_reflects_live_events(client, db):
    admin = login(client, "admin")
    before = client.get("/api/dashboard", headers=admin).json()["metrics"]["pending_requests"]
    neha = login(client, "neha.gupta")
    client.post("/api/requests", headers=neha, json={"resource_id": rid(db, "RES-FIN-003"), "permissions": ["READ"],
                                                     "purpose": "COMPLIANCE_AUDIT", "duration_hours": 8,
                                                     "justification": "SOX walkthrough for the payments reconciliation control."})
    after = client.get("/api/dashboard", headers=admin).json()
    assert after["metrics"]["pending_requests"] == before + 1
    assert after["recent_activity"][0]["action"] in ("REQUEST_CREATED", "RISK_ASSESSED")
    personal = client.get("/api/dashboard", headers=neha).json()
    assert personal["personal"] is True
