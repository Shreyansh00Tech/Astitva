"""Simulated model / dataset / database workspaces: every permission is enforced by the API, per user, live."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.context import SYSTEM
from app.models import AccessGrant, AuditEvent, Resource, utcnow
from app.services import grants as grant_svc
from tests.conftest import login, user_by_email

FRAUD = "RES-DS-001"      # model: READ EXECUTE WRITE ADMIN
SUPPORT = "RES-DS-003"    # dataset: READ EXECUTE WRITE DELETE
TXN = "RES-FIN-002"       # dataset: READ EXECUTE WRITE DELETE ADMIN
HRDB = "RES-HR-001"       # database, ABAC: HR + SEC only


def rid(db, code):
    return db.execute(select(Resource.id).where(Resource.code == code)).scalar_one()


def fresh_grant(db, local, code, perms, hours=4, purpose="MODEL_TESTING"):
    """Clear the user's grants on the resource, then give exactly `perms`."""
    u = user_by_email(db, local)
    r = rid(db, code)
    for g in db.execute(select(AccessGrant).where(AccessGrant.user_id == u.id, AccessGrant.resource_id == r,
                                                  AccessGrant.status == "ACTIVE")).scalars():
        grant_svc.revoke_grant(db, SYSTEM, g, "test reset")
    g, _ = grant_svc.create_grant(db, SYSTEM, user_id=u.id, resource_id=r, permissions=perms, purpose=purpose, hours=hours)
    db.commit()
    return g, r


def codes(resp):
    return resp.status_code, (resp.json().get("detail") or {}).get("code") if resp.status_code >= 400 else None


FRAUD_INPUT = {"amount_inr": 64000, "txns_last_hour": 7, "device_risk": "High", "location_anomaly": True, "account_age_days": 21}


@pytest.mark.parametrize("perms", [["READ"], ["READ", "EXECUTE"], ["READ", "WRITE"], ["READ", "EXECUTE", "WRITE", "ADMIN"], ["EXECUTE"]])
def test_model_permission_matrix(client, db, perms):
    _, r = fresh_grant(db, "neha.gupta", FRAUD, perms)
    h = login(client, "neha.gupta")
    ov = client.get(f"/api/workspace/{r}", headers=h)
    assert ov.status_code == 200, ov.text
    body = ov.json()
    assert body["permissions"] == perms
    a = body["actions"]
    assert a["run_prediction"] == ("EXECUTE" in perms)
    assert a["edit_metadata"] == ("WRITE" in perms)
    assert a["admin"] == ("ADMIN" in perms)
    assert not a["add_record"] and not a["delete_record"]
    assert ("playground" in body["model"]) == ("EXECUTE" in perms)
    assert ("metrics" in body["model"]) == ("READ" in perms)
    if "READ" in perms:
        assert body["model"]["metrics_label"] == "SIMULATED METRICS — NOT VALIDATED"
        assert body["model"]["status"] == "DEMO ONLY"

    p = client.post(f"/api/workspace/{r}/predict", headers=h, json={"values": FRAUD_INPUT})
    if "EXECUTE" in perms:
        assert p.status_code == 200
        out = p.json()
        assert out["label"] == "SIMULATED OUTPUT — NOT A REAL MODEL PREDICTION"
        assert out["predicted_class"] == "Suspicious" and out["score"] >= 0.7
        # deterministic: same input, same output
        assert client.post(f"/api/workspace/{r}/predict", headers=h, json={"values": FRAUD_INPUT}).json()["score"] == out["score"]
    else:
        assert codes(p) == (403, "PERMISSION_NOT_GRANTED")

    m = client.patch(f"/api/workspace/{r}/metadata", headers=h, json={"monitoring_notes": "Weekly drift review (demo)."})
    assert m.status_code == (200 if "WRITE" in perms else 403)
    adm = client.get(f"/api/workspace/{r}/admin", headers=h)
    assert adm.status_code == (200 if "ADMIN" in perms else 403)


@pytest.mark.parametrize("perms", [["READ"], ["READ", "EXECUTE"], ["READ", "WRITE"], ["READ", "WRITE", "DELETE"],
                                   ["READ", "EXECUTE", "WRITE", "DELETE"]])
def test_dataset_permission_matrix(client, db, perms):
    _, r = fresh_grant(db, "rahul.sharma", SUPPORT, perms, purpose="CUSTOMER_SUPPORT")
    h = login(client, "rahul.sharma")
    body = client.get(f"/api/workspace/{r}", headers=h).json()
    a = body["actions"]
    assert (a["run_query"], a["add_record"], a["edit_record"], a["delete_record"]) == (
        "EXECUTE" in perms, "WRITE" in perms, "WRITE" in perms, "DELETE" in perms)
    assert body["dataset"]["status"] == "DEMO DATA ONLY" and body["dataset"]["columns"] == 6

    # READ: search, sort and paginate are always available with READ
    page = client.get(f"/api/workspace/{r}/records?q=billing&sort=priority&dir=desc&size=5", headers=h).json()
    assert page["rows"] and all(x["data"]["category"] == "Billing" for x in page["rows"])
    first = client.get(f"/api/workspace/{r}/records?size=5", headers=h).json()["rows"][0]

    q = client.post(f"/api/workspace/{r}/query", headers=h, json={"group_by": "priority", "metric": "count"})
    assert q.status_code == (200 if "EXECUTE" in perms else 403)

    new = {"category": "Refund", "priority": "High", "sentiment": "Negative", "status": "Open", "resolution_hours": None}
    add = client.post(f"/api/workspace/{r}/records", headers=h, json={"values": new})
    assert add.status_code == (201 if "WRITE" in perms else 403)
    ed = client.patch(f"/api/workspace/{r}/records/{first['id']}", headers=h, json={"values": {"status": "Closed", "resolution_hours": 3}})
    assert ed.status_code == (200 if "WRITE" in perms else 403)
    de = client.delete(f"/api/workspace/{r}/records/{first['id']}", headers=h)
    assert de.status_code == (200 if "DELETE" in perms else 403)


def test_statistics_match_the_rows(client, db):
    _, r = fresh_grant(db, "rahul.sharma", SUPPORT, ["READ", "WRITE"], purpose="CUSTOMER_SUPPORT")
    h = login(client, "rahul.sharma")
    rows = client.get(f"/api/workspace/{r}/records?size=50&page=1", headers=h).json()
    total = rows["total"]
    allrows = []
    for p in range(1, rows["pages"] + 1):
        allrows += client.get(f"/api/workspace/{r}/records?size=50&page={p}", headers=h).json()["rows"]
    st = client.get(f"/api/workspace/{r}/stats", headers=h).json()
    assert st["records"] == total == len(allrows)
    assert st["missing_values"] == sum(1 for x in allrows for v in x["data"].values() if v is None)
    high = next(c["count"] for c in st["categories"]["priority"] if c["value"] == "High")
    assert high == sum(1 for x in allrows if x["data"]["priority"] == "High")
    # a write is reflected in the statistics
    client.post(f"/api/workspace/{r}/records", headers=h, json={"values": {"category": "Billing", "priority": "High",
                                                                          "sentiment": "Neutral", "status": "Open"}})
    st2 = client.get(f"/api/workspace/{r}/stats", headers=h).json()
    assert st2["records"] == total + 1
    assert next(c["count"] for c in st2["categories"]["priority"] if c["value"] == "High") == high + 1


def test_invalid_records_are_rejected(client, db):
    _, r = fresh_grant(db, "rahul.sharma", SUPPORT, ["READ", "WRITE"], purpose="CUSTOMER_SUPPORT")
    h = login(client, "rahul.sharma")
    bad = client.post(f"/api/workspace/{r}/records", headers=h, json={"values": {"category": "Hacking", "priority": "High",
                                                                                "sentiment": "Neutral", "status": "Open"}})
    assert bad.status_code == 422
    key = client.post(f"/api/workspace/{r}/records", headers=h, json={"values": {"ticket_id": "X", "category": "Billing"}})
    assert key.status_code == 422


def test_no_grant_and_other_users_grant_are_refused(client, db):
    g, r = fresh_grant(db, "neha.gupta", TXN, ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"], purpose="ANALYTICS_REPORTING")
    rahul = user_by_email(db, "rahul.sharma")
    for x in db.execute(select(AccessGrant).where(AccessGrant.user_id == rahul.id, AccessGrant.resource_id == r,
                                                  AccessGrant.status == "ACTIVE")).scalars():
        grant_svc.revoke_grant(db, SYSTEM, x, "test reset")
    db.commit()
    h = login(client, "rahul.sharma")
    assert codes(client.get(f"/api/workspace/{r}", headers=h)) == (403, "NO_ACTIVE_GRANT")
    assert client.get(f"/api/workspace/{r}/records", headers=h).status_code == 403
    assert client.post(f"/api/workspace/{r}/query", headers=h, json={}).status_code == 403
    # Neha's record ids do not help Rahul either
    neha = login(client, "neha.gupta")
    rec = client.get(f"/api/workspace/{r}/records", headers=neha).json()["rows"][0]
    assert client.delete(f"/api/workspace/{r}/records/{rec['id']}", headers=h).status_code == 403
    denied = db.execute(select(AuditEvent).where(AuditEvent.action == "WORKSPACE_ACTION_DENIED",
                                                 AuditEvent.actor_id == rahul.id)).first()
    assert denied


def test_expired_grant_returns_403_and_is_expired(client, db):
    g, r = fresh_grant(db, "neha.gupta", FRAUD, ["READ", "EXECUTE"])
    h = login(client, "neha.gupta")
    assert client.get(f"/api/workspace/{r}", headers=h).status_code == 200
    g.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert codes(client.post(f"/api/workspace/{r}/predict", headers=h, json={"values": FRAUD_INPUT})) == (403, "GRANT_EXPIRED")
    db.expire_all()
    assert db.get(AccessGrant, g.id).status == "EXPIRED"
    assert codes(client.get(f"/api/workspace/{r}", headers=h)) == (403, "NO_ACTIVE_GRANT")


def test_revoked_and_narrowed_grants_stop_working_immediately(client, db):
    g, r = fresh_grant(db, "neha.gupta", FRAUD, ["READ", "EXECUTE"])
    h = login(client, "neha.gupta")
    assert client.post(f"/api/workspace/{r}/predict", headers=h, json={"values": FRAUD_INPUT}).status_code == 200
    grant_svc.restrict_grant(db, SYSTEM, g, ["READ"], "EXECUTE no longer needed")
    db.commit()
    assert codes(client.post(f"/api/workspace/{r}/predict", headers=h, json={"values": FRAUD_INPUT})) == (403, "PERMISSION_NOT_GRANTED")
    assert "playground" not in client.get(f"/api/workspace/{r}", headers=h).json()["model"]
    grant_svc.revoke_grant(db, SYSTEM, g, "Project finished")
    db.commit()
    assert client.get(f"/api/workspace/{r}", headers=h).status_code == 403


def test_abac_still_applies_inside_the_workspace(client, db):
    # A grant on the HR database held by someone outside HR/SEC (e.g. created before a policy change) does not open it.
    _, r = fresh_grant(db, "rahul.sharma", HRDB, ["READ"], purpose="COMPLIANCE_AUDIT")
    h = login(client, "rahul.sharma")
    assert codes(client.get(f"/api/workspace/{r}", headers=h)) == (403, "POLICY_DENIED")


def test_admin_masking_hides_identifiers_from_non_admins(client, db):
    _, r = fresh_grant(db, "neha.gupta", TXN, ["READ", "ADMIN"], purpose="ANALYTICS_REPORTING")
    _, _ = fresh_grant(db, "rahul.sharma", TXN, ["READ"], purpose="ANALYTICS_REPORTING")
    neha, rahul = login(client, "neha.gupta"), login(client, "rahul.sharma")
    assert client.patch(f"/api/workspace/{r}/settings", headers=rahul, json={"mask_identifiers": True}).status_code == 403
    assert client.patch(f"/api/workspace/{r}/settings", headers=neha, json={"mask_identifiers": True}).status_code == 200
    r_row = client.get(f"/api/workspace/{r}/records", headers=rahul).json()["rows"][0]["data"]
    n_row = client.get(f"/api/workspace/{r}/records", headers=neha).json()["rows"][0]["data"]
    assert "*" in r_row["customer_ref"] and "*" not in n_row["customer_ref"]
    roster = client.get(f"/api/workspace/{r}/admin", headers=neha).json()
    assert {x["user"]["name"] for x in roster["holders"]} >= {"Neha Gupta", "Rahul Sharma"}
    client.patch(f"/api/workspace/{r}/settings", headers=neha, json={"mask_identifiers": False})


def test_database_tables_and_models_have_their_own_content(client, db):
    _, r = fresh_grant(db, "admin", HRDB, ["READ"], purpose="COMPLIANCE_AUDIT")
    h = login(client, "admin")
    body = client.get(f"/api/workspace/{r}", headers=h).json()
    assert [t["name"] for t in body["database"]["tables"]] == ["employees", "compensation_bands", "leave_balances"]
    assert all(t["records"] > 0 for t in body["database"]["tables"])
    rows = client.get(f"/api/workspace/{r}/records?table=compensation_bands", headers=h).json()
    assert rows["total"] == 5
    assert client.get(f"/api/workspace/{r}/records?table=gl_entries", headers=h).status_code == 404


def test_approval_puts_exact_scope_in_active_access_and_pending_or_rejected_do_not(client, db):
    from tests.conftest import set_routing
    from tests.test_scenarios import act, approve_all, submit

    set_routing(False)
    u = user_by_email(db, "rahul.sharma")
    r = rid(db, "RES-FIN-004")  # Loan Approval Model
    for x in db.execute(select(AccessGrant).where(AccessGrant.user_id == u.id, AccessGrant.resource_id == r)).scalars():
        grant_svc.revoke_grant(db, SYSTEM, x, "test reset")
    db.commit()
    rahul, priya, meera = login(client, "rahul.sharma"), login(client, "priya.desai"), login(client, "admin")

    # pending: nothing in Active Access, workspace refused
    req = submit(client, rahul, r, ["READ", "EXECUTE"], "MODEL_TESTING", hours=48)
    assert not [g for g in client.get("/api/grants?scope=mine", headers=rahul).json() if g["resource"]["id"] == r]
    assert client.get(f"/api/workspace/{r}", headers=rahul).status_code == 403

    # rejected: still nothing
    rej = act(client, priya, req["id"], "REJECT", comment="Not needed for this project")
    assert rej.status_code == 200 and rej.json()["status"] == "REJECTED"
    assert client.get(f"/api/workspace/{r}", headers=rahul).status_code == 403

    # approved after narrowing to READ: exact scope and expiry show up and are enforced
    req = submit(client, rahul, r, ["READ", "EXECUTE"], "MODEL_TESTING", hours=48)
    n = act(client, priya, req["id"], "NARROW_SCOPE", comment="Read only for now", permissions=["READ"], duration_hours=24)
    assert n.status_code == 200, n.text
    done = approve_all(client, n.json(), {"MANAGER": priya, "RISK": meera})
    assert done["status"] == "APPROVED"
    mine = [g for g in client.get("/api/grants?scope=mine", headers=rahul).json() if g["resource"]["id"] == r]
    assert len(mine) == 1 and mine[0]["permissions"] == ["READ"]
    g = db.get(AccessGrant, mine[0]["id"])
    assert abs((g.expires_at - g.granted_at).total_seconds() - 24 * 3600) < 5
    ws = client.get(f"/api/workspace/{r}", headers=rahul).json()
    assert ws["permissions"] == ["READ"] and "playground" not in ws["model"]
    assert client.post(f"/api/workspace/{r}/predict", headers=rahul, json={"values": {}}).status_code == 403
    # Nobody else gets it
    assert client.get(f"/api/workspace/{r}", headers=login(client, "neha.gupta")).status_code == 403
