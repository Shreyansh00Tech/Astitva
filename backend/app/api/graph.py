"""Access dependency graph API. Only the Manager and the Security Manager hold graph:read (checked here, not just in
the UI). A Manager sees and revokes only their own team's grants; agents and API links need the Security Manager."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import _can_manage_grant
from app.api.deps import CurrentUser, require
from app.core.db import get_db
from app.models import AccessGrant, AgentPermission, Resource, ResourceDependency
from app.services import dependency

router = APIRouter(prefix="/api", tags=["dependency-graph"])


def _viewer(cu: CurrentUser) -> dependency.Viewer:
    return dependency.Viewer(user_id=cu.id, full_view=cu.has("grants:read_all"),
                             can_revoke_agents=cu.has("agents:manage"), can_revoke_services=cu.has("grants:revoke_any"),
                             can_manage_grant=lambda g: _can_manage_grant(cu, g))


def _resource(db: Session, resource_id: str) -> Resource:
    r = db.get(Resource, resource_id)
    if not r:
        raise HTTPException(404, "Resource not found")
    return r


@router.get("/dependency-graph/resources")
def graph_resources(cu: CurrentUser = Depends(require("graph:read")), db: Session = Depends(get_db)):
    """Resource picker for the graph page, with quick blast-radius counts."""
    grants = dict(db.execute(select(AccessGrant.resource_id, func.count()).where(AccessGrant.status == "ACTIVE")
                             .group_by(AccessGrant.resource_id)).all())
    agents = dict(db.execute(select(AgentPermission.resource_id, func.count()).where(AgentPermission.revoked_at.is_(None))
                             .group_by(AgentPermission.resource_id)).all())
    links = dict(db.execute(select(ResourceDependency.resource_id, func.count())
                            .where(ResourceDependency.suspended_at.is_(None)).group_by(ResourceDependency.resource_id)).all())
    rows = db.execute(select(Resource).order_by(Resource.code)).scalars().all()
    return [{"id": r.id, "code": r.code, "name": r.name, "type": r.resource_type, "sensitivity": r.sensitivity,
             "active_grants": grants.get(r.id, 0), "agents": agents.get(r.id, 0), "apis": links.get(r.id, 0)} for r in rows]


@router.get("/resources/{resource_id}/dependency-graph")
def get_graph(resource_id: str, cu: CurrentUser = Depends(require("graph:read")), db: Session = Depends(get_db)):
    return dependency.build_graph(db, _resource(db, resource_id), _viewer(cu))


class RevokeAccessIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    users: bool = True
    agents: bool = False
    services: bool = False
    node_ids: list[str] | None = Field(default=None, max_length=200)


@router.post("/resources/{resource_id}/revoke-access")
def revoke_access(resource_id: str, body: RevokeAccessIn, cu: CurrentUser = Depends(require("graph:read")),
                  db: Session = Depends(get_db)):
    r = _resource(db, resource_id)
    v = _viewer(cu)
    try:
        result = dependency.revoke_resource_access(db, cu.actor, r, v, reason=body.reason, users=body.users,
                                                   agents=body.agents, services=body.services, node_ids=body.node_ids)
    except dependency.RevokeError as e:
        db.rollback()
        raise HTTPException(e.status, e.message)
    db.commit()
    return {"revoked": result, "graph": dependency.build_graph(db, r, v)}


class RestoreIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/dependencies/{dependency_id}/restore")
def restore_link(dependency_id: str, body: RestoreIn, cu: CurrentUser = Depends(require("graph:read", "grants:revoke_any")),
                 db: Session = Depends(get_db)):
    d = db.get(ResourceDependency, dependency_id)
    if not d:
        raise HTTPException(404, "API link not found")
    try:
        dependency.restore_service_link(db, cu.actor, d, body.reason)
    except dependency.RevokeError as e:
        raise HTTPException(e.status, e.message)
    db.commit()
    return dependency.build_graph(db, _resource(db, d.resource_id), _viewer(cu))
