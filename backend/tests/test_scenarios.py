"""End-to-end functional tests for the 15 acceptance scenarios (real API, real Postgres, Redis via fakeredis)."""
from datetime import timedelta

import pyotp
from sqlalchemy import select, text

from app.models import (
    AccessGrant,
    AccessRequest,
    AccessReview,
    AccessToken,
    AiAgent,
    AuditEvent,
    DriftFinding,
    Notification,
    Resource,
    SecurityAlert,
    Task,
    TaskEvent,
    UserSession,
    utcnow,
)
from app.seed import AGENT_KEYS, DEMO_PASSWORD
from tests.conftest import email, latest_otp, login, user_by_email


def res_id(db, code):
    return db.execute(select(Resource.id).where(Resource.code == code)).scalar_one()


def submit(client, h, resource_id, perms, purpose, hours=24, why="Validating quarterly model outputs against the audited holdout set."):
    r = client.post("/api/requests", headers=h, json={"resource_id": resource_id, "permissions": perms, "purpose": purpose,
                                                      "justification": why, "duration_hours": hours})
    assert r.status_code == 201, r.text
    return r.json()


def act(client, h, rid, action="APPROVE", **kw):
    return client.post(f"/api/approvals/{rid}/action", headers=h, json={"action": action, **kw})


def approve_all(client, req, approvers: dict):
    """approvers: stage -> headers. Approve every remaining stage in order."""
    cur = req
    while cur["status"] == "PENDING":
        r = act(client, approvers[cur["current_stage"]], cur["id"], comment="ok")
        assert r.status_code == 200, r.text
        cur = r.json()
    return cur


def reveal(client, h, grant_id):
    r = client.post(f"/api/grants/{grant_id}/token/reveal", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def grant_for(db, request_id):
    return db.execute(select(AccessGrant).where(AccessGrant.request_id == request_id)).scalar_one()


def gw(client, h, resource_id, token, action, purpose):
    hdrs = dict(h)
    if token:
        hdrs["X-Access-Token"] = token
    return client.post(f"/api/gateway/resources/{resource_id}/access", headers=hdrs, json={"action": action, "purpose": purpose})


# ---------------------------------------------------------------- TEST 1
def test_01_full_approval_chain_activates_access(client, db):
    neha = login(client, "neha.gupta")
    manager, security = login(client, "priya.desai"), login(client, "admin")
    rid = res_id(db, "RES-FIN-001")
    req = submit(client, neha, rid, ["READ"], "MODEL_TESTING", 24)
    assert req["required_stages"] == ["MANAGER", "RISK"]  # Manager -> Security Manager
    assert req["risk"]["score"] >= 0 and req["risk"]["level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    # The Security Manager cannot jump the queue
    r = act(client, security, req["id"])
    assert r.status_code == 403 and r.json()["detail"]["rule"] == "STAGE_AUTHORITY"
    r = act(client, manager, req["id"])
    assert r.status_code == 200 and r.json()["current_stage"] == "RISK"
    r = act(client, security, req["id"])
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "APPROVED" and [a["stage"] for a in done["approvals"]] == ["MANAGER", "RISK"]

    g = grant_for(db, req["id"])
    assert g.status == "ACTIVE" and g.permissions == ["READ"] and g.purpose == "MODEL_TESTING"
    tok = db.execute(select(AccessToken).where(AccessToken.grant_id == g.id)).scalar_one()
    assert tok.token_hint.startswith("SIM-ACCESS-") and tok.request_id == req["id"] and tok.approval_ref
    token = reveal(client, neha, g.id)
    r = gw(client, neha, rid, token, "READ", "MODEL_TESTING")
    assert r.status_code == 200 and r.json()["decision"] == "ALLOWED"
    actions = set(db.execute(select(AuditEvent.action).where(AuditEvent.request_id == req["id"])).scalars())
    assert {"REQUEST_CREATED", "RISK_ASSESSED", "REQUEST_APPROVE", "GRANT_ACTIVATED", "RESOURCE_ACCESS_ALLOWED"} <= actions
    kinds = set(db.execute(select(Notification.kind).where(Notification.user_id == g.user_id)).scalars())
    assert "REQUEST_APPROVED" in kinds


# ---------------------------------------------------------------- TEST 2
def test_02_requester_cannot_approve_own_request(client, db):
    priya = login(client, "priya.desai")  # the Manager has approvals:act; her own request goes to security review
    req = submit(client, priya, res_id(db, "RES-DS-002"), ["READ"], "ANALYTICS_REPORTING", 24)
    assert req["required_stages"] == ["RISK"]
    r = act(client, priya, req["id"])
    assert r.status_code == 403
    assert r.json()["detail"]["rule"] == "SELF_APPROVAL"
    assert db.execute(select(AuditEvent).where(AuditEvent.request_id == req["id"],
                                               AuditEvent.action == "SOD_VIOLATION_BLOCKED")).scalars().first()
    # A plain requester has no approval permission at all
    rahul = login(client, "rahul.sharma")
    assert act(client, rahul, req["id"]).status_code == 403
    assert db.get(AccessRequest, req["id"]).status == "PENDING"
    # The Security Manager has nobody independent to review their own request -> refused up front
    sec = login(client, "admin")
    r = client.post("/api/requests", headers=sec, json={"resource_id": res_id(db, "RES-ENG-001"), "permissions": ["READ"],
                                                        "purpose": "ANALYTICS_REPORTING", "duration_hours": 8,
                                                        "justification": "Self-serve attempt by the Security Manager."})
    assert r.status_code == 409 and r.json()["detail"]["rule"] == "SELF_APPROVAL"


# ---------------------------------------------------------------- TEST 3
def test_03_expired_access_token_is_rejected(client, db):
    neha = login(client, "kavya.reddy")
    rid = res_id(db, "RES-FIN-002")
    req = submit(client, neha, rid, ["READ"], "COMPLIANCE_AUDIT", 8)
    approve_all(client, req, {"MANAGER": login(client, "priya.desai"), "RISK": login(client, "admin")})
    g = grant_for(db, req["id"])
    token = reveal(client, neha, g.id)
    assert gw(client, neha, rid, token, "READ", "COMPLIANCE_AUDIT").status_code == 200
    # Time passes: move expiry into the past
    db.execute(text("UPDATE access_grants SET expires_at = now() - interval '1 minute' WHERE id=:i"), {"i": g.id})
    db.execute(text("UPDATE access_tokens SET expires_at = now() - interval '1 minute' WHERE grant_id=:i"), {"i": g.id})
    db.commit()
    r = gw(client, neha, rid, token, "READ", "COMPLIANCE_AUDIT")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "TOKEN_EXPIRED"
    db.expire_all()
    assert db.get(AccessGrant, g.id).status == "EXPIRED"
    assert db.execute(select(AccessToken).where(AccessToken.grant_id == g.id)).scalar_one().revoked_at is not None
    r = gw(client, neha, rid, token, "READ", "COMPLIANCE_AUDIT")
    assert r.status_code == 403


def test_03b_scheduler_expires_grants(client, db):
    from app.services.grants import expire_due

    g = db.execute(select(AccessGrant).where(AccessGrant.status == "ACTIVE", AccessGrant.source == "REQUEST",
                                             AccessGrant.expires_at.is_not(None))).scalars().first()
    g.expires_at = utcnow() - timedelta(seconds=5)
    db.commit()
    assert expire_due(db) >= 1
    db.commit()
    assert db.get(AccessGrant, g.id).status == "EXPIRED"


# ---------------------------------------------------------------- TEST 4
def test_04_unauthorized_resource_access_blocked(client, db):
    rahul = login(client, "rahul.sharma")
    ledger = res_id(db, "RES-FIN-003")
    r = gw(client, rahul, ledger, None, "READ", "ANALYTICS_REPORTING")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NO_TOKEN"
    r = gw(client, rahul, ledger, "SIM-ACCESS-FAKE123.notreal", "READ", "ANALYTICS_REPORTING")
    assert r.json()["detail"]["code"] == "INVALID_TOKEN"
    # A real token for another resource does not open this one
    g = db.execute(select(AccessGrant).join(AccessToken, AccessToken.grant_id == AccessGrant.id).where(
        AccessGrant.user_id == user_by_email(db, "rahul.sharma").id, AccessGrant.status == "ACTIVE")).scalars().first()
    token = reveal(client, rahul, g.id)
    r = gw(client, rahul, ledger, token, "READ", g.purpose)
    assert r.json()["detail"]["code"] == "TOKEN_RESOURCE_MISMATCH"
    # ABAC: engineers cannot even request HR data
    r = client.post("/api/requests", headers=rahul, json={"resource_id": res_id(db, "RES-HR-001"), "permissions": ["READ"],
                                                          "purpose": "COMPLIANCE_AUDIT", "duration_hours": 8,
                                                          "justification": "Checking employee records for a report."})
    assert r.status_code == 403 and r.json()["detail"]["rule"] == "ABAC"
    # Frontend hiding is not the control: requesters are refused admin APIs server-side
    assert client.get("/api/audit/events", headers=rahul).status_code == 403
    assert client.get("/api/policies", headers=rahul).status_code == 403


# ---------------------------------------------------------------- TEST 5
def test_05_token_is_purpose_identity_and_permission_bound(client, db):
    neha = login(client, "neha.gupta")
    rid = res_id(db, "RES-FIN-001")
    g = db.execute(select(AccessGrant).where(AccessGrant.user_id == user_by_email(db, "neha.gupta").id,
                                             AccessGrant.resource_id == rid, AccessGrant.status == "ACTIVE")).scalars().first()
    if g is None:  # create one if test 1 did not run
        req = submit(client, neha, rid, ["READ"], "MODEL_TESTING", 24)
        approve_all(client, req, {"MANAGER": login(client, "priya.desai"), "RISK": login(client, "admin")})
        g = grant_for(db, req["id"])
    token = reveal(client, neha, g.id)
    r = gw(client, neha, rid, token, "READ", "MODEL_TRAINING")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "TOKEN_PURPOSE_MISMATCH"
    r = gw(client, neha, rid, token, "WRITE", "MODEL_TESTING")
    assert r.json()["detail"]["code"] == "PERMISSION_NOT_GRANTED"
    other = login(client, "rahul.sharma")
    r = gw(client, other, rid, token, "READ", "MODEL_TESTING")
    assert r.json()["detail"]["code"] == "TOKEN_IDENTITY_MISMATCH"
    assert db.execute(select(SecurityAlert).where(SecurityAlert.category == "TOKEN_MISUSE",
                                                  SecurityAlert.user_id == user_by_email(db, "rahul.sharma").id)
                      .order_by(SecurityAlert.created_at.desc())).scalars().first()
    assert gw(client, neha, rid, token, "READ", "MODEL_TESTING").status_code == 200


# ---------------------------------------------------------------- TEST 6
def test_06_conflicting_approvals_blocked(client, db):
    kh = login(client, "kavya.reddy")
    req = submit(client, kh, res_id(db, "RES-ENG-002"), ["READ"], "FEATURE_DEVELOPMENT", 24,
                 "Check the payroll export job against the dev database schema change.")
    priya = login(client, "priya.desai")
    admin = login(client, "admin")
    # The Security Manager is not Kavya's manager and cannot do the manager review
    r = act(client, admin, req["id"])
    assert r.status_code == 403 and r.json()["detail"]["rule"] == "STAGE_AUTHORITY"
    # Priya approves as manager...
    r = act(client, priya, req["id"])
    assert r.status_code == 200 and r.json()["current_stage"] == "RISK"
    # ...and cannot also give the security approval
    r = act(client, priya, req["id"])
    assert r.status_code == 403 and r.json()["detail"]["rule"] in ("STAGE_AUTHORITY", "MANAGER_DUAL_ROLE", "INDEPENDENT_REVIEWERS")
    # Admin-defined conflicting-role policy is enforced too
    p = client.post("/api/policies", headers=admin, json={"name": "Security admins need a second reviewer", "policy_type": "SOD",
                                                          "rules": {"kind": "ROLE_CONFLICT", "roles": ["SECURITY_ADMIN", "RISK_REVIEWER"],
                                                                    "stages": ["RISK"]}})
    assert p.status_code == 201
    r = act(client, admin, req["id"])
    assert r.status_code == 403 and r.json()["detail"]["rule"].startswith("POLICY:")
    assert client.delete(f"/api/policies/{p.json()['id']}", headers=admin).status_code == 200
    r = act(client, admin, req["id"])
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


# ---------------------------------------------------------------- TEST 7
def test_07_permission_drift_detected_and_remediated(client, db):
    kavya = user_by_email(db, "kavya.reddy")
    hr = res_id(db, "RES-HR-001")
    db.add(AccessGrant(user_id=kavya.id, resource_id=hr, permissions=["READ", "WRITE", "DELETE", "ADMIN"],
                       purpose="PAYROLL_PROCESSING", source="LEGACY", granted_at=utcnow() - timedelta(days=60)))
    db.commit()
    admin = login(client, "admin")
    r = client.post("/api/drift/scan", headers=admin)
    assert r.status_code == 200
    f = db.execute(select(DriftFinding).where(DriftFinding.user_id == kavya.id, DriftFinding.resource_id == hr,
                                              DriftFinding.status == "OPEN")).scalar_one()
    assert {"WRITE", "DELETE", "ADMIN"} <= set(f.excess_permissions)
    assert f.severity in ("HIGH", "CRITICAL") and f.drift_score > 60
    assert any("escalation" in i.lower() for i in f.issues)
    assert db.execute(select(SecurityAlert).where(SecurityAlert.category == "PERMISSION_DRIFT",
                                                  SecurityAlert.user_id == kavya.id)).scalars().first()
    # Requester cannot remove permissions; the resource owner can
    assert client.post(f"/api/drift/{f.id}/action", headers=login(client, "rahul.sharma"), json={"action": "REVOKE"}).status_code == 403
    r = client.post(f"/api/drift/{f.id}/action", headers=login(client, "admin"),
                    json={"action": "RESTRICT", "permissions": ["READ"], "comment": "Back to baseline"})
    assert r.status_code == 200 and r.json()["status"] == "REMEDIATED"
    db.expire_all()
    perms = set()
    for g in db.execute(select(AccessGrant).where(AccessGrant.user_id == kavya.id, AccessGrant.resource_id == hr,
                                                  AccessGrant.status == "ACTIVE")).scalars():
        perms |= set(g.permissions)
    assert perms == {"READ"}


# ---------------------------------------------------------------- TEST 8
def test_08_breakglass_alert_monitor_and_revoke(client, db):
    from app.models import User

    eng = user_by_email(db, "priya.desai")  # Engineering staff are eligible for break-glass
    h = login(client, eng.email)
    dev = res_id(db, "RES-ENG-002")
    r = client.post("/api/emergency", headers=h, json={
        "resource_id": dev, "permissions": ["READ", "WRITE"], "incident_ref": "INC-50001", "duration_minutes": 30,
        "justification": "Orders service outage: need to inspect and repair corrupted migration state now."})
    assert r.status_code == 201, r.text
    es = r.json()
    assert es["status"] == "ACTIVE" and es["remaining_seconds"] > 0
    alert = db.execute(select(SecurityAlert).where(SecurityAlert.category == "BREAKGLASS", SecurityAlert.user_id == eng.id)
                       .order_by(SecurityAlert.created_at.desc())).scalars().first()
    assert alert and alert.severity == "CRITICAL"
    admin_u = user_by_email(db, "admin")
    assert db.execute(select(Notification).where(Notification.user_id == admin_u.id,
                                                 Notification.kind == "SECURITY_ALERT")).scalars().first()
    # Using the emergency token is logged against the session
    assert gw(client, h, dev, es["token"], "WRITE", "INCIDENT_RESPONSE").status_code == 200
    admin = login(client, "admin")
    actions = client.get(f"/api/emergency/{es['id']}/actions", headers=admin).json()
    assert len(actions) == 1 and actions[0]["action"] == "WRITE"
    monitor = client.get("/api/emergency?scope=all", headers=admin).json()
    assert any(s["id"] == es["id"] and s["status"] == "ACTIVE" for s in monitor["sessions"])
    # Immediate revoke
    r = client.post(f"/api/emergency/{es['id']}/revoke", headers=admin, json={"reason": "Incident resolved"})
    assert r.status_code == 200 and r.json()["status"] == "REVOKED"
    r = gw(client, h, dev, es["token"], "READ", "INCIDENT_RESPONSE")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "TOKEN_REVOKED"
    # Post-incident review: not by the user themselves; Security Admin completes it
    assert client.post(f"/api/emergency/{es['id']}/review", headers=h,
                       json={"outcome": "JUSTIFIED", "notes": "self review attempt"}).status_code == 403
    r = client.post(f"/api/emergency/{es['id']}/review", headers=admin,
                    json={"outcome": "JUSTIFIED", "notes": "Actions matched runbook RB-12."})
    assert r.status_code == 200 and r.json()["review_status"] == "COMPLETED"
    acts = set(db.execute(select(AuditEvent.action).where(AuditEvent.target_id == es["ref"])).scalars())
    assert {"BREAKGLASS_ACTIVATED", "BREAKGLASS_REVOKED", "BREAKGLASS_REVIEWED"} <= acts
    # Finance staff are not eligible
    r = client.post("/api/emergency", headers=login(client, "neha.gupta"), json={
        "resource_id": res_id(db, "RES-FIN-003"), "permissions": ["READ"], "incident_ref": "INC-50002",
        "justification": "Trying to get quick access to the ledger outside of the normal process."})
    assert r.status_code == 403


# ---------------------------------------------------------------- TEST 9
def test_09_audit_tampering_detected(client, db):
    admin = login(client, "admin")
    r = client.get("/api/audit/verify", headers=admin)
    assert r.status_code == 200 and r.json()["valid"] is True
    original = db.execute(text("SELECT reason FROM audit_events WHERE seq = 10")).scalar()
    db.execute(text("UPDATE audit_events SET reason = 'tampered by insider' WHERE seq = 10"))
    db.commit()
    r = client.get("/api/audit/verify", headers=admin).json()
    assert r["valid"] is False and r["first_invalid_seq"] == 10 and "modified" in r["problem"]
    db.execute(text("UPDATE audit_events SET reason = :r WHERE seq = 10"), {"r": original})
    db.commit()
    assert client.get("/api/audit/verify", headers=admin).json()["valid"] is True
    # Deleting a record breaks the chain too (checked inside a rolled-back transaction)
    from app.services.audit import verify_chain

    db.execute(text("DELETE FROM audit_events WHERE seq = 20"))
    res = verify_chain(db)
    db.rollback()
    assert res["valid"] is False and res["first_invalid_seq"] == 21
    csv = client.get("/api/audit/export.csv", headers=admin)
    assert csv.status_code == 200 and csv.text.startswith("seq,occurred_at")


# ---------------------------------------------------------------- TEST 10
def test_10_five_failures_lock_account_temporarily(client, db):
    target = email("neha.gupta")
    codes = []
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": target, "password": "Wrong-Password-123!"})
        codes.append(r.status_code)
    assert codes[:4] == [401, 401, 401, 401] and codes[4] == 429
    # Correct password is refused during the temporary lockout, with a generic message
    r = client.post("/api/auth/login", json={"email": target, "password": DEMO_PASSWORD})
    assert r.status_code == 429 and r.json()["code"] == "LOCKED" and int(r.headers["Retry-After"]) > 0
    assert "password" not in r.json()["detail"].lower()
    assert db.execute(select(SecurityAlert).where(SecurityAlert.category == "BRUTE_FORCE",
                                                  SecurityAlert.user_id == user_by_email(db, "neha.gupta").id)).scalars().first()
    # Lock is temporary (TTL) - not permanent
    from tests.conftest import FAKE
    from app.services.auth import _ekey

    ttl = FAKE.ttl(f"astitva:lock:{_ekey(target)}")
    assert 0 < ttl <= 60
    FAKE.delete(f"astitva:lock:{_ekey(target)}")
    assert client.post("/api/auth/login", json={"email": target, "password": DEMO_PASSWORD}).status_code == 200


def test_10b_generic_errors_and_ip_token_bucket(client):
    a = client.post("/api/auth/login", json={"email": email("nobody.here"), "password": "Whatever-123!"}).json()
    b = client.post("/api/auth/login", json={"email": email("rahul.sharma"), "password": "Whatever-123!"}).json()
    assert a["detail"] == b["detail"] == "Invalid email or password."
    statuses = [client.post("/api/auth/login", json={"email": email(f"spray{i}"), "password": "Summer2026!x"}).status_code
                for i in range(25)]
    assert 429 in statuses  # IP token bucket (and credential-stuffing tightening) kicks in


# ---------------------------------------------------------------- TEST 11
def test_11_mfa_cannot_be_bypassed(client):
    r = client.post("/api/auth/login", json={"email": email("kavya.reddy"), "password": DEMO_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] and "astitva_at" not in r.cookies  # no session before MFA
    mfa_token = body["mfa_token"]
    # The pending-MFA token is not an access token
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {mfa_token}"}).status_code == 401
    # A forged access token is rejected
    import jwt as pyjwt

    forged = pyjwt.encode({"sub": "x", "sid": "y", "typ": "access", "iss": "astitva", "exp": 9999999999}, "guess", "HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    # Wrong codes fail; after 5 the challenge is burned even for the right code
    for _ in range(5):
        r = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "method": "EMAIL", "code": "000000"})
        assert r.status_code in (401, 429)
    good = latest_otp(email("kavya.reddy"))
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "method": "EMAIL", "code": good})
    assert r.status_code in (401, 429)
    # Method switching does not help: TOTP not enrolled -> refused
    from tests.conftest import FAKE

    FAKE.flushall()
    r = client.post("/api/auth/login", json={"email": email("kavya.reddy"), "password": DEMO_PASSWORD}).json()
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "method": "TOTP", "code": "123456"}).status_code == 401


def test_11b_totp_enrolment_and_login(client):
    h = login(client, "kavya.reddy")
    setup = client.post("/api/auth/mfa/totp/setup", headers=h).json()
    assert setup["qr_svg"].startswith("data:image/svg+xml")
    totp = pyotp.TOTP(setup["secret"])
    r = client.post("/api/auth/mfa/totp/confirm", headers=h, json={"code": totp.now()})
    assert r.status_code == 200 and len(r.json()["backup_codes"]) == 10
    backup = r.json()["backup_codes"][0]
    from tests.conftest import FAKE

    FAKE.flushall()
    lr = client.post("/api/auth/login", json={"email": email("kavya.reddy"), "password": DEMO_PASSWORD}).json()
    assert "TOTP" in lr["methods"]
    # Replay of the enrolment code is refused; a backup code works once
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": lr["mfa_token"], "method": "TOTP", "code": totp.now()}).status_code == 401
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": lr["mfa_token"], "method": "BACKUP_CODE", "code": backup})
    assert r.status_code == 200
    FAKE.flushall()
    lr = client.post("/api/auth/login", json={"email": email("kavya.reddy"), "password": DEMO_PASSWORD}).json()
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": lr["mfa_token"], "method": "BACKUP_CODE", "code": backup}).status_code == 401


# ---------------------------------------------------------------- TEST 12
def test_12_support_agent_blocked_from_financial_database(client, db):
    sup = db.execute(select(AiAgent).where(AiAgent.code == "AGT-SUP-01")).scalar_one()
    hdr = {"X-Agent-Id": sup.code, "X-Agent-Key": AGENT_KEYS["AGT-SUP-01"]}
    r = client.post("/api/agent-gateway/invoke", headers=hdr, json={"resource": "RES-FIN-003", "action": "READ", "tool": "kb.search"})
    assert r.status_code == 403
    assert r.json()["detail"]["message"] == "Agent is not authorized to access this resource."
    alert = db.execute(select(SecurityAlert).where(SecurityAlert.category == "AGENT_UNAUTHORIZED", SecurityAlert.agent_id == sup.id)
                       .order_by(SecurityAlert.created_at.desc())).scalars().first()
    assert alert and alert.severity == "HIGH"
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "AGENT_ACCESS_DENIED", AuditEvent.actor_id == sup.id)
                      .order_by(AuditEvent.seq.desc())).scalars().first()
    ok = client.post("/api/agent-gateway/invoke", headers=hdr, json={"resource": "RES-DS-003", "action": "READ", "tool": "kb.search"})
    assert ok.status_code == 200 and ok.json()["decision"] == "ALLOWED"
    bad_tool = client.post("/api/agent-gateway/invoke", headers=hdr, json={"resource": "RES-DS-003", "action": "READ", "tool": "sql.write"})
    assert bad_tool.json()["detail"]["code"] == "TOOL_NOT_ALLOWED"
    write = client.post("/api/agent-gateway/invoke", headers=hdr, json={"resource": "RES-DS-003", "action": "WRITE", "tool": "kb.search"})
    assert write.json()["detail"]["code"] == "PERMISSION_NOT_GRANTED"
    assert client.post("/api/agent-gateway/invoke", headers={**hdr, "X-Agent-Key": "stolen"},
                       json={"resource": "RES-DS-003", "action": "READ", "tool": "kb.search"}).status_code == 401
    # Agents can never be given ADMIN
    admin = login(client, "admin")
    assert client.put(f"/api/agents/{sup.id}/permissions", headers=admin,
                      json={"resource_id": res_id(db, "RES-DS-003"), "permissions": ["ADMIN"]}).status_code == 422


# ---------------------------------------------------------------- TEST 13
def test_13_deactivation_revokes_grants_and_sessions(client, db):
    from app.models import User

    victim = user_by_email(db, "kavya.reddy")
    vh = login(client, victim.email)
    assert client.get("/api/auth/me", headers=vh).status_code == 200
    active_before = db.execute(select(AccessGrant).where(AccessGrant.user_id == victim.id, AccessGrant.status == "ACTIVE")).scalars().all()
    assert active_before
    admin = login(client, "admin")
    r = client.post(f"/api/employees/{victim.id}/deactivate", headers=admin, json={"reason": "Resigned - last working day"})
    assert r.status_code == 200
    assert r.json()["grants_revoked"] == len(active_before) and r.json()["sessions_revoked"] >= 1
    db.expire_all()
    assert not db.execute(select(AccessGrant).where(AccessGrant.user_id == victim.id, AccessGrant.status == "ACTIVE")).scalars().all()
    assert all(s.revoked_at for s in db.execute(select(UserSession).where(UserSession.user_id == victim.id)).scalars())
    assert all(t.revoked_at for t in db.execute(select(AccessToken).where(AccessToken.user_id == victim.id)).scalars())
    assert client.get("/api/auth/me", headers=vh).status_code == 401
    assert client.post("/api/auth/login", json={"email": victim.email, "password": DEMO_PASSWORD}).status_code == 401


# ---------------------------------------------------------------- TEST 14
def test_14_manager_analytics_match_recorded_task_events(client, db):
    priya = login(client, "priya.desai")
    rahul = user_by_email(db, "rahul.sharma")
    prof = client.get(f"/api/employees/{rahul.id}", headers=priya).json()
    verified = db.execute(select(Task).where(Task.assignee_id == rahul.id, Task.status == "DONE",
                                             Task.verified_at.is_not(None))).scalars().all()
    assert prof["work"]["verified_tasks"] == len(verified)
    charts = client.get(f"/api/employees/{rahul.id}/analytics", headers=priya).json()
    since = utcnow() - timedelta(days=30)
    db_daily = len(db.execute(select(TaskEvent).where(TaskEvent.user_id == rahul.id, TaskEvent.occurred_at >= since)).scalars().all())
    api_daily = sum(d["events"] for d in charts["daily_activity"])
    assert abs(api_daily - db_daily) <= 2  # boundary day rounding only
    lb = client.get("/api/leaderboard", headers=priya).json()["rows"]
    row = next(r for r in lb if r["user_id"] == rahul.id)
    in_window = [t for t in verified if t.completed_at >= utcnow() - timedelta(days=90)]
    assert row["verified_tasks"] == len(in_window)
    # Record a new verified task -> analytics move accordingly
    proj = prof["projects"][0]["id"]
    now = utcnow()
    t = Task(code="TSK-TEST-1", project_id=proj, assignee_id=rahul.id, title="Verified test task", status="DONE",
             priority="HIGH", due_at=now + timedelta(days=1), completed_at=now, verified_at=now, quality_score=5.0,
             verified_by_id=user_by_email(db, "priya.desai").id)
    db.add(t)
    db.flush()
    db.add(TaskEvent(task_id=t.id, user_id=rahul.id, project_id=proj, event_type="VERIFIED", occurred_at=now))
    db.commit()
    prof2 = client.get(f"/api/employees/{rahul.id}", headers=priya).json()
    assert prof2["work"]["verified_tasks"] == len(verified) + 1
    ev = client.get(f"/api/employees/{rahul.id}/evidence", headers=priya).json()
    assert any(e["code"] == "TSK-TEST-1" and e["verified"] for e in ev)
    # Scope: Priya sees her own team (incl. Neha) but not the Security Manager; requesters cannot use it at all
    neha = user_by_email(db, "neha.gupta")
    assert client.get(f"/api/employees/{neha.id}", headers=priya).status_code == 200
    sec = user_by_email(db, "admin")
    assert client.get(f"/api/employees/{sec.id}", headers=priya).status_code == 404
    assert client.get("/api/employees", headers=login(client, "rahul.sharma")).status_code == 403


# ---------------------------------------------------------------- TEST 15
def test_15_overdue_recertification_raises_alert(client, db):
    admin = login(client, "admin")
    r = client.post("/api/reviews/campaigns", headers=admin, json={"name": "Test cycle"})
    assert r.status_code == 201
    priya_u = user_by_email(db, "priya.desai")
    db.execute(text("UPDATE access_reviews SET due_at = now() - interval '1 day', overdue_alerted = false "
                    "WHERE reviewer_id = :r AND status = 'PENDING'"), {"r": priya_u.id})
    db.commit()
    r = client.post("/api/reviews/process-overdue", headers=admin)
    assert r.status_code == 200 and r.json()["overdue_flagged"] > 0
    assert db.execute(select(SecurityAlert).where(SecurityAlert.category == "RECERT_OVERDUE",
                                                  SecurityAlert.user_id == priya_u.id)).scalars().first()
    assert db.execute(select(Notification).where(Notification.user_id == priya_u.id,
                                                 Notification.kind == "RECERTIFICATION_OVERDUE")).scalars().first()
    priya = login(client, "priya.desai")
    items = client.get("/api/reviews?status=PENDING", headers=priya).json()["reviews"]
    assert items and all(i["overdue"] for i in items)
    item = next(i for i in items if i["grant_status"] == "ACTIVE")
    r = client.post(f"/api/reviews/{item['id']}/decide", headers=priya, json={"decision": "REVOKE", "comment": "No longer needed"})
    assert r.status_code == 200 and r.json()["status"] == "REVOKED"
    rv = db.get(AccessReview, item["id"])
    db.refresh(rv)
    assert db.get(AccessGrant, rv.grant_id).status == "REVOKED"
