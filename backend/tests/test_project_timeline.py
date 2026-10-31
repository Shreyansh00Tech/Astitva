"""Access is bound to the employee's current project: it never outlives the project end date."""
from datetime import timedelta

from sqlalchemy import select

from app.core.context import SYSTEM
from app.models import AccessGrant, AccessToken, Project, Resource
from app.services import grants as grant_svc
from app.services import projects
from tests.conftest import login, user_by_email


def test_seeded_grant_is_capped_at_project_end(db):
    """Rahul asked for 30 days on the recommendation model; Atlas ends in 15, so the grant ends with Atlas."""
    rahul = user_by_email(db, "rahul.sharma")
    atlas = db.execute(select(Project).where(Project.code == "PRJ-ATLAS")).scalar_one()
    assert projects.current_project(db, rahul.id).id == atlas.id
    res = db.execute(select(Resource).where(Resource.code == "RES-DS-002")).scalar_one()
    g = db.execute(select(AccessGrant).where(AccessGrant.user_id == rahul.id, AccessGrant.resource_id == res.id,
                                             AccessGrant.status == "ACTIVE", AccessGrant.request_id.is_not(None))).scalar_one()
    assert g.project_id == atlas.id
    assert g.expires_at == atlas.end_date
    tok = db.execute(select(AccessToken).where(AccessToken.grant_id == g.id)).scalars().first()
    assert tok.expires_at == atlas.end_date  # the token cannot outlive the project either


def test_short_grant_is_not_extended_and_emergency_is_not_capped(db):
    neha = user_by_email(db, "neha.gupta")
    falcon = projects.current_project(db, neha.id)
    assert falcon.code == "PRJ-FALCON"
    res = db.execute(select(Resource).where(Resource.code == "RES-FIN-001")).scalar_one()
    g, _ = grant_svc.create_grant(db, SYSTEM, user_id=neha.id, resource_id=res.id, permissions=["READ"],
                                  purpose="MODEL_TESTING", hours=8)
    assert g.project_id == falcon.id and g.expires_at < falcon.end_date  # shorter than the project: unchanged
    g2, _ = grant_svc.create_grant(db, SYSTEM, user_id=neha.id, resource_id=res.id, permissions=["READ"],
                                   purpose="MODEL_TESTING", hours=24 * 60)
    assert g2.expires_at == falcon.end_date
    expires, capped = projects.cap_expiry(None, falcon.end_date + timedelta(days=5))
    assert capped is False and expires == falcon.end_date + timedelta(days=5)  # no project: no cap
    db.rollback()


def test_request_records_project_and_overview_timeline(client, db):
    kavya = login(client, "kavya.reddy")
    data = client.get("/api/me/project-timeline", headers=kavya).json()
    p = data["project"]
    assert p["code"] == "PRJ-PULSE"
    assert p["start_date"] < p["submission_date"] < p["end_date"]
    assert any(m["is_me"] for m in data["team"]) and any(m["role"] == "Project Manager" for m in data["team"])
    for g in data["grants"]:
        assert g["expires_at"] is not None  # standing access is counted separately, not drawn
        if g["linked"]:
            assert g["within_project"]


def test_project_timeline_visibility(client, db):
    rahul = login(client, "rahul.sharma")
    neha_id = user_by_email(db, "neha.gupta").id
    assert client.get(f"/api/employees/{neha_id}/project-timeline", headers=rahul).status_code == 403
    priya = login(client, "priya.desai")
    r = client.get(f"/api/employees/{neha_id}/project-timeline", headers=priya)
    assert r.status_code == 200 and r.json()["project"]["code"] == "PRJ-FALCON"
