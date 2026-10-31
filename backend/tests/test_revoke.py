"""Removing granted access: the manager (own team) or the Security Manager can revoke fully or drop single permissions."""
from sqlalchemy import select

from app.models import AccessGrant, AccessToken, AuditEvent, Notification
from tests.conftest import login, user_by_email


def active_grant(db, local, min_perms=1):
    u = user_by_email(db, local)
    gs = db.execute(select(AccessGrant).where(AccessGrant.user_id == u.id, AccessGrant.status == "ACTIVE",
                                              AccessGrant.is_emergency.is_(False), AccessGrant.request_id.is_not(None))
                    .order_by(AccessGrant.granted_at.desc())).scalars().all()
    g = next((g for g in gs if len(g.permissions) >= min_perms), None)
    assert g, f"seed has no active request grant for {local} with >= {min_perms} permissions"
    return g


def test_manager_removes_one_permission_then_revokes(client, db):
    g = active_grant(db, "kavya.reddy", 2)
    gid, rid, perms = g.id, g.request_id, list(g.permissions)
    priya = login(client, "priya.desai")
    team = client.get("/api/grants?scope=team", headers=priya).json()
    assert next(x for x in team if x["id"] == gid)["can_manage"] is True
    # Narrow: keep only the first permission
    r = client.post(f"/api/grants/{gid}/restrict", headers=priya, json={"permissions": perms[:1], "reason": "Write no longer needed"})
    assert r.status_code == 200, r.text and r.json()["permissions"] == perms[:1]
    db.expire_all()
    assert db.get(AccessGrant, gid).permissions == perms[:1]
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "GRANT_RESTRICTED", AuditEvent.request_id == rid)).first()
    # Old token is dead, a narrowed one exists
    live = db.execute(select(AccessToken).where(AccessToken.grant_id == gid, AccessToken.revoked_at.is_(None))).scalars().all()
    assert len(live) == 1 and live[0].permissions == perms[:1]
    # Full revoke
    r = client.post(f"/api/grants/{gid}/revoke", headers=priya, json={"reason": "Project finished"})
    assert r.status_code == 200 and r.json()["status"] == "REVOKED"
    kavya = login(client, "kavya.reddy")
    req = client.get(f"/api/requests/{rid}", headers=kavya).json()
    assert req["access"]["status"] == "REVOKED" and req["access"]["revoked_by"]["name"] == "Priya Desai"
    assert req["access"]["revoke_reason"] == "Project finished" and req["can_manage_access"] is False
    assert any(x["id"] == rid and x["access"]["status"] == "REVOKED" for x in client.get("/api/requests", headers=kavya).json())
    n = db.execute(select(Notification).where(Notification.user_id == user_by_email(db, "kavya.reddy").id,
                                              Notification.kind == "ACCESS_REVOKED")).first()
    assert n
    # Already revoked -> 409 (or 404 for restrict)
    assert client.post(f"/api/grants/{gid}/revoke", headers=priya, json={"reason": "again"}).status_code == 409


def test_employees_cannot_revoke_their_own_or_others_access(client, db):
    g = active_grant(db, "rahul.sharma", 2)
    gid = g.id
    for who in ("kavya.reddy", "rahul.sharma"):
        h = login(client, who)
        assert client.post(f"/api/grants/{gid}/revoke", headers=h, json={"reason": "try it"}).status_code == 403
        assert client.post(f"/api/grants/{gid}/restrict", headers=h, json={"permissions": g.permissions[:1], "reason": "try it"}).status_code == 403
    rahul = login(client, "rahul.sharma")
    assert next(x for x in client.get("/api/grants?scope=mine", headers=rahul).json() if x["id"] == gid)["can_manage"] is False
    assert client.get(f"/api/requests/{g.request_id}", headers=rahul).json()["can_manage_access"] is False
    db.expire_all()
    assert db.get(AccessGrant, gid).status == "ACTIVE"


def test_security_manager_can_revoke_any_grant(client, db):
    g = active_grant(db, "rahul.sharma")
    admin = login(client, "admin")
    allg = client.get("/api/grants?scope=all", headers=admin).json()
    assert next(x for x in allg if x["id"] == g.id)["can_manage"] is True
    r = client.post(f"/api/grants/{g.id}/revoke", headers=admin, json={"reason": "Security review finding"})
    assert r.status_code == 200 and r.json()["revoked_by"]["name"] == "Meera Krishnan"
