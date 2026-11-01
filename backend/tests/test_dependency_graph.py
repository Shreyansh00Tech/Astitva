"""Access dependency graph: blast radius of revoking a model, visible only to the Manager and the Security Manager."""
from sqlalchemy import select

from app.core.context import SYSTEM
from app.models import AccessGrant, AccessToken, AgentPermission, AiAgent, AuditEvent, Resource
from app.services import gateway
from app.services.grants import create_grant
from tests.conftest import login, user_by_email


def res(db, code):
    return db.execute(select(Resource).where(Resource.code == code)).scalar_one()


def agent(db, code):
    return db.execute(select(AiAgent).where(AiAgent.code == code)).scalar_one()


def node(graph, nid):
    return next((n for n in graph["nodes"] if n["id"] == nid), None)


def by_label(graph, label):
    return next((n for n in graph["nodes"] if n["label"] == label), None)


def test_only_manager_and_security_manager_can_see_or_use_the_graph(client, db):
    r = res(db, "RES-DS-002")
    for who in ("kavya.reddy", "rahul.sharma"):
        h = login(client, who)
        assert client.get("/api/dependency-graph/resources", headers=h).status_code == 403
        assert client.get(f"/api/resources/{r.id}/dependency-graph", headers=h).status_code == 403
        assert client.post(f"/api/resources/{r.id}/revoke-access", headers=h, json={"reason": "try it"}).status_code == 403
    for who in ("priya.desai", "admin"):
        h = login(client, who)
        assert client.get("/api/dependency-graph/resources", headers=h).status_code == 200
        assert client.get(f"/api/resources/{r.id}/dependency-graph", headers=h).status_code == 200
    me = client.get("/api/auth/me", headers=login(client, "kavya.reddy")).json()
    assert "graph:read" not in me.get("permissions", [])


def test_graph_shows_users_agents_apis_and_indirect_impact(client, db):
    r = res(db, "RES-DS-002")
    g = client.get(f"/api/resources/{r.id}/dependency-graph", headers=login(client, "admin")).json()
    assert g["resource"]["code"] == "RES-DS-002" and g["viewer"]["full_view"] is True
    sup = node(g, f"agent:{agent(db, 'AGT-SUP-01').id}")
    assert sup and sup["impact"] == "DIRECT" and sup["status"] == "ACTIVE"
    api = by_label(g, "Storefront Recommendations API")
    assert api["type"] == "API" and api["impact"] == "DIRECT" and api["criticality"] == "HIGH"
    analytics = node(g, f"res:{res(db, 'RES-ENG-001').id}")
    assert analytics["type"] == "API" and analytics["impact"] == "DIRECT"
    # Second level: who uses the Internal Analytics API is indirectly affected
    dev = node(g, f"agent:{agent(db, 'AGT-DEV-01').id}")
    assert dev and dev["impact"] == "INDIRECT"
    assert by_label(g, "Product Metrics Dashboard API")["impact"] == "INDIRECT"
    assert g["summary"]["agents"] >= 1 and g["summary"]["apis"] >= 2 and g["summary"]["indirect_agents"] >= 1
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


def test_manager_sees_only_own_team_by_name(client, db):
    r = res(db, "RES-ENG-001")
    admin_u, priya = user_by_email(db, "admin"), user_by_email(db, "priya.desai")
    g1, _ = create_grant(db, SYSTEM, user_id=admin_u.id, resource_id=r.id, permissions=["READ"], purpose="ANALYTICS_REPORTING", hours=24)
    db.commit()
    g = client.get(f"/api/resources/{r.id}/dependency-graph", headers=login(client, "priya.desai")).json()
    assert g["viewer"]["full_view"] is False and g["viewer"]["can_revoke_agents"] is False
    users = [n for n in g["nodes"] if n["type"] == "USER"]
    team = {u.id for u in db.query(type(priya)).filter_by(manager_id=priya.id)}
    assert users and all(n["user_id"] in team for n in users)
    assert not any("Meera" in n["label"] for n in g["nodes"])
    group = next(n for n in g["nodes"] if n["type"] == "USER_GROUP")
    assert group["count"] >= 1 and group["can_revoke"] is False
    db.get(AccessGrant, g1.id).status = "REVOKED"
    db.commit()


def test_manager_revokes_only_team_grants_and_graph_updates(client, db):
    r = res(db, "RES-DS-002")
    kavya, admin_u = user_by_email(db, "kavya.reddy"), user_by_email(db, "admin")
    gk, _ = create_grant(db, SYSTEM, user_id=kavya.id, resource_id=r.id, permissions=["READ", "EXECUTE"], purpose="MODEL_TESTING", hours=24)
    ga, _ = create_grant(db, SYSTEM, user_id=admin_u.id, resource_id=r.id, permissions=["READ"], purpose="MODEL_TESTING", hours=24)
    db.commit()
    priya = login(client, "priya.desai")
    before = client.get(f"/api/resources/{r.id}/dependency-graph", headers=priya).json()
    assert node(before, f"user:{kavya.id}")["can_revoke"] is True and before["summary"]["active_tokens"] >= 1
    # A manager cannot cut agents or API links
    assert client.post(f"/api/resources/{r.id}/revoke-access", headers=priya,
                       json={"reason": "Model retired", "agents": True}).status_code == 403
    # Naming someone outside the team does not let a manager revoke them
    picked = [f"user:{kavya.id}", f"user:{admin_u.id}"]
    resp = client.post(f"/api/resources/{r.id}/revoke-access", headers=priya, json={"reason": "Model retired", "node_ids": picked})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Kavya Reddy" in body["revoked"]["users"] and body["revoked"]["skipped"] >= 1
    after = body["graph"]
    assert node(after, f"user:{kavya.id}")["status"] == "REVOKED"
    db.expire_all()
    assert db.get(AccessGrant, gk.id).status == "REVOKED"
    assert db.get(AccessGrant, ga.id).status == "ACTIVE"  # outside Priya's team: untouched
    assert not db.execute(select(AccessToken).where(AccessToken.grant_id == gk.id, AccessToken.revoked_at.is_(None))).first()
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "RESOURCE_ACCESS_REVOKED",
                                               AuditEvent.resource_id == r.id)).first()
    # Nothing left that Priya may revoke -> 409
    assert client.post(f"/api/resources/{r.id}/revoke-access", headers=priya,
                       json={"reason": "again", "node_ids": picked}).status_code == 409
    db.get(AccessGrant, ga.id).status = "REVOKED"
    db.commit()


def test_security_manager_cuts_agent_and_api_then_restores(client, db):
    r = res(db, "RES-DS-002")
    sup = agent(db, "AGT-SUP-01")
    analytics = res(db, "RES-ENG-001")
    admin = login(client, "admin")
    g = client.get(f"/api/resources/{r.id}/dependency-graph", headers=admin).json()
    store = by_label(g, "Storefront Recommendations API")
    picked = [f"agent:{sup.id}", store["id"], f"res:{analytics.id}"]
    resp = client.post(f"/api/resources/{r.id}/revoke-access", headers=admin,
                       json={"reason": "Model compromised", "users": False, "agents": True, "services": True, "node_ids": picked})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["revoked"]["agents"] == ["Customer Support AI Agent"]
    assert set(out["revoked"]["services"]) == {"Storefront Recommendations API", "Recommendation metrics feed"}
    after = out["graph"]
    assert node(after, f"agent:{sup.id}")["status"] == "REVOKED"
    assert node(after, store["id"])["status"] == "SUSPENDED" and node(after, store["id"])["can_restore"] is True
    assert node(after, f"res:{analytics.id}")["status"] == "SUSPENDED"
    assert node(after, f"agent:{agent(db, 'AGT-DEV-01').id}")["status"] == "DEGRADED"  # indirect, through the cut link
    # The gateway now denies the agent on this model
    db.expire_all()
    d = gateway.enforce_agent_access(db, db.get(AiAgent, sup.id), r.id, "EXECUTE", "model.invoke", "127.0.0.1")
    assert not d.allowed and d.code == "PERMISSION_REVOKED"
    db.rollback()
    # Restore the API links and re-grant the agent (normal AI Security flow)
    for nid in (store["id"], f"res:{analytics.id}"):
        dep_id = node(after, nid)["dependency_id"]
        assert client.post(f"/api/dependencies/{dep_id}/restore", headers=admin, json={"reason": "Incident closed"}).status_code == 200
    assert client.post(f"/api/dependencies/{store['dependency_id']}/restore", headers=admin,
                       json={"reason": "again"}).status_code == 409
    assert client.post(f"/api/dependencies/{store['dependency_id']}/restore", headers=login(client, "priya.desai"),
                       json={"reason": "manager try"}).status_code == 403
    r2 = client.put(f"/api/agents/{sup.id}/permissions", headers=admin, json={"resource_id": r.id, "permissions": ["EXECUTE"]})
    assert r2.status_code == 200, r2.text
    db.expire_all()
    p = db.execute(select(AgentPermission).where(AgentPermission.agent_id == sup.id, AgentPermission.resource_id == r.id)).scalar_one()
    assert p.revoked_at is None
    final = client.get(f"/api/resources/{r.id}/dependency-graph", headers=admin).json()
    assert node(final, f"agent:{sup.id}")["status"] == "ACTIVE" and node(final, store["id"])["status"] == "ACTIVE"


def test_user_reached_directly_and_indirectly_shows_revoked_after(client, db):
    """Kavya uses the Recommendation model directly and the Internal Analytics API (fed by the model): after revoking
    her direct grant she must show as revoked, not stay 'active' because of the indirect path."""
    model, analytics = res(db, "RES-DS-002"), res(db, "RES-ENG-001")
    kavya = user_by_email(db, "kavya.reddy")
    create_grant(db, SYSTEM, user_id=kavya.id, resource_id=model.id, permissions=["READ"], purpose="MODEL_TESTING", hours=24)
    create_grant(db, SYSTEM, user_id=kavya.id, resource_id=analytics.id, permissions=["READ"], purpose="ANALYTICS_REPORTING", hours=24)
    db.commit()
    priya = login(client, "priya.desai")
    r = client.post(f"/api/resources/{model.id}/revoke-access", headers=priya,
                    json={"reason": "Model retired", "node_ids": [f"user:{kavya.id}"]})
    assert r.status_code == 200, r.text
    n = node(r.json()["graph"], f"user:{kavya.id}")
    assert n["impact"] == "DIRECT" and n["status"] == "REVOKED" and n["can_revoke"] is False
