"""Access requests, approvals, grants and the resource enforcement gateway."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require, require_any
from app.api.serializers import grant_out, request_out, resource_full, user_brief
from app.core.catalog import PERMISSIONS, PURPOSES
from app.core.db import get_db
from app.models import AccessGrant, AccessRequest, AccessToken, AiAgent, Resource, User, utcnow
from app.security import crypto
from app.services import analytics, audit, gateway, grants as grant_svc, sod, workflow

router = APIRouter(prefix="/api", tags=["access"])


def _wf(e: workflow.WorkflowError):
    raise HTTPException(e.status, {"message": e.message, "rule": e.rule})


@router.get("/catalog")
def catalog(cu: CurrentUser = Depends(get_current_user)):
    return {"permissions": PERMISSIONS,
            "purposes": [{"code": k, "label": v[0], "least_privilege": v[1]} for k, v in PURPOSES.items()]}


# ------------------------------------------------------------------ requests
class RequestIn(BaseModel):
    resource_id: str
    permissions: list[str] = Field(min_length=1)
    purpose: str
    justification: str = Field(min_length=10, max_length=2000)
    duration_hours: int = Field(ge=1, le=2160)
    deadline_at: datetime | None = None   # ISO 8601 with timezone
    business_impact: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


@router.post("/requests", status_code=201)
def create_request(body: RequestIn, cu: CurrentUser = Depends(require("requests:create")), db: Session = Depends(get_db)):
    try:
        req = workflow.submit(db, cu.actor, resource_id=body.resource_id, permissions=body.permissions,
                              purpose=body.purpose, justification=body.justification, duration_hours=body.duration_hours,
                              deadline_at=body.deadline_at, business_impact=body.business_impact)
    except workflow.WorkflowError as e:
        _wf(e)
    return request_out(db.get(AccessRequest, req.id), include_detail=True)


@router.get("/requests")
def list_requests(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                  cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if scope == "all":
        if not cu.has("requests:read_all"):
            raise HTTPException(403, "Missing permission: requests:read_all")
    else:
        q = q.where(AccessRequest.requester_id == cu.id)
    if status:
        q = q.where(AccessRequest.status == status)
    return [request_out(r) for r in db.execute(q.limit(300)).scalars()]


def _can_view_request(db: Session, cu: CurrentUser, req: AccessRequest) -> bool:
    if req.requester_id == cu.id or cu.has("requests:read_all"):
        return True
    if req.requester.manager_id == cu.id:
        return True
    if cu.id in (req.resource.owner_id, req.resource.backup_owner_id):
        return True
    return any(a.approver_id == cu.id for a in req.approvals)


@router.get("/requests/{request_id}")
def get_request(request_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.get(AccessRequest, request_id)
    if not req or not _can_view_request(db, cu, req):
        raise HTTPException(404, "Request not found")
    out = request_out(req, include_detail=True)
    out["can_act"] = bool(req.status == "PENDING" and req.current_stage and cu.has("approvals:act")
                          and sod.eligible_for_stage(db, cu.user, req, req.current_stage))
    if req.status == "PENDING" and req.current_stage and cu.has("approvals:act") and not out["can_act"]:
        try:
            sod.check(db, cu.user, req, req.current_stage)
        except sod.SodViolation as v:
            out["blocked_reason"] = {"rule": v.rule, "message": v.message}
    out["stage_approvers"] = [user_brief(u) for u in workflow.stage_approvers(db, req)] if req.current_stage else []
    g = req.grant
    out["can_manage_access"] = bool(g and g.status == "ACTIVE" and _can_manage_grant(cu, g))
    return out


class ResubmitIn(RequestIn):
    resource_id: str | None = None  # resource cannot change on resubmission


@router.post("/requests/{request_id}/resubmit")
def resubmit(request_id: str, body: ResubmitIn, cu: CurrentUser = Depends(require("requests:create")),
             db: Session = Depends(get_db)):
    try:
        req = workflow.resubmit(db, cu.actor, request_id, permissions=body.permissions, purpose=body.purpose,
                                justification=body.justification, duration_hours=body.duration_hours,
                                deadline_at=body.deadline_at, business_impact=body.business_impact)
    except workflow.WorkflowError as e:
        _wf(e)
    return request_out(req, include_detail=True)


class PriorityInputsIn(BaseModel):
    deadline_at: datetime | None = None
    business_impact: str = Field(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


@router.patch("/requests/{request_id}/priority-inputs")
def update_priority_inputs(request_id: str, body: PriorityInputsIn, cu: CurrentUser = Depends(require("requests:create")),
                           db: Session = Depends(get_db)):
    try:
        req = workflow.update_priority_inputs(db, cu.actor, request_id, deadline_at=body.deadline_at,
                                              business_impact=body.business_impact)
    except workflow.WorkflowError as e:
        _wf(e)
    return request_out(req, include_detail=True)


@router.post("/requests/{request_id}/cancel")
def cancel(request_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return request_out(workflow.cancel(db, cu.actor, request_id))
    except workflow.WorkflowError as e:
        _wf(e)


# ------------------------------------------------------------------ approvals
QUEUE_SORTS = {
    # highest priority first; ties: earliest deadline (none last), then longest waiting
    "priority": lambda i: (-i["priority"]["score"], i["deadline_at"] is None, i["deadline_at"] or "", i["created_at"]),
    "deadline": lambda i: (i["deadline_at"] is None, i["deadline_at"] or "", -i["priority"]["score"]),
    "waiting": lambda i: (i["created_at"], -i["priority"]["score"]),
}


def _queue_filter(item: dict, f: str | None) -> bool:
    p = item["priority"]
    if not f:
        return True
    if f == "overdue":
        return p["overdue"]
    if f == "approaching":
        return p["approaching"]
    return p["level"] == f


@router.get("/approvals/queue")
def approval_queue(sort: str = Query("priority", pattern="^(priority|deadline|waiting)$"),
                   filter: str | None = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL|overdue|approaching)$"),
                   cu: CurrentUser = Depends(require("approvals:read")), db: Session = Depends(get_db)):
    pending = db.execute(select(AccessRequest).where(AccessRequest.status == "PENDING")
                         .order_by(AccessRequest.created_at)).scalars().all()
    mine, others = [], []
    now = utcnow()
    for r in pending:
        item = request_out(r, now=now)
        if not _queue_filter(item, filter):
            continue
        item["stage_approvers"] = [u.full_name for u in workflow.stage_approvers(db, r)]
        if cu.has("approvals:act") and sod.eligible_for_stage(db, cu.user, r, r.current_stage):
            mine.append(item)
        elif cu.has("requests:read_all") or r.requester.manager_id == cu.id or cu.id in (r.resource.owner_id, r.resource.backup_owner_id):
            others.append(item)
    mine.sort(key=QUEUE_SORTS[sort])
    others.sort(key=QUEUE_SORTS[sort])
    history = db.execute(select(AccessRequest).join(AccessRequest.approvals)
                         .where(AccessRequest.approvals.any(approver_id=cu.id))
                         .order_by(AccessRequest.updated_at.desc()).limit(50)).scalars().unique().all()
    return {"actionable": mine, "watching": others, "history": [request_out(r) for r in history]}


class ActionIn(BaseModel):
    action: str = Field(pattern="^(APPROVE|REJECT|NARROW_SCOPE|REQUEST_MODIFICATION)$")
    comment: str | None = Field(default=None, max_length=2000)
    permissions: list[str] | None = None
    duration_hours: int | None = Field(default=None, ge=1, le=2160)


@router.post("/approvals/{request_id}/action")
def approval_action(request_id: str, body: ActionIn, cu: CurrentUser = Depends(require("approvals:act")),
                    db: Session = Depends(get_db)):
    try:
        req = workflow.act(db, cu.actor, request_id, body.action, body.comment, body.permissions, body.duration_hours)
    except workflow.WorkflowError as e:
        _wf(e)
    return request_out(req, include_detail=True)


@router.get("/approvals/{request_id}/context")
def approval_context(request_id: str, cu: CurrentUser = Depends(require("approvals:read")), db: Session = Depends(get_db)):
    """Employee intelligence panel shown to approvers. Work performance is informational only."""
    req = db.get(AccessRequest, request_id)
    if not req or not _can_view_request(db, cu, req):
        raise HTTPException(404, "Request not found")
    u = req.requester
    stats = analytics.work_stats(db, u.id)
    charts = analytics.employee_charts(db, u.id)
    active = db.execute(select(AccessGrant).where(AccessGrant.user_id == u.id, AccessGrant.status == "ACTIVE")).scalars().all()
    from app.models import ProjectMember, Project

    projects = db.execute(select(Project.name).join(ProjectMember, ProjectMember.project_id == Project.id)
                          .where(ProjectMember.user_id == u.id)).scalars().all()
    from app.models import SecurityAlert

    violations = db.execute(select(SecurityAlert).where(SecurityAlert.user_id == u.id, SecurityAlert.category.in_(
        ["POLICY_VIOLATION", "UNAUTHORIZED_ACCESS", "TOKEN_MISUSE", "BREAKGLASS_MISUSE", "SOD_VIOLATION"]))).scalars().all()
    return {
        "employee": {**user_brief(u), "joined_at": u.joined_at, "manager": user_brief(u.manager) if u.manager else None,
                     "device_trust": u.device_trust},
        "work": {**stats, "assigned_projects": len(projects), "projects": projects,
                 "activity_level_30d": analytics.activity_level(db, u)},
        "security": {"policy_violations": len(violations), "active_grants": len(active),
                     "denied_operations": stats["denied_operations"],
                     "active_grant_list": [grant_out(g) for g in active]},
        "recommendation": {"permissions": req.risk.recommended_permissions if req.risk else req.approved_permissions,
                           "duration_hours": req.risk.recommended_duration_hours if req.risk else req.approved_duration_hours,
                           "basis": "Least-privilege recommendation from the risk engine. Productivity scores are never used "
                                    "to grant permissions."},
        "weekly_productivity": charts["weekly_productivity"],
    }


# ------------------------------------------------------------------ grants
@router.get("/grants")
def list_grants(scope: str = Query("mine", pattern="^(mine|team|owned|all)$"), status: str | None = "ACTIVE",
                cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(AccessGrant).order_by(AccessGrant.granted_at.desc())
    if scope == "mine":
        q = q.where(AccessGrant.user_id == cu.id)
    elif scope == "team":
        if not cu.has("grants:read_team"):
            raise HTTPException(403, "Missing permission: grants:read_team")
        q = q.join(User, User.id == AccessGrant.user_id).where(User.manager_id == cu.id)
    elif scope == "owned":
        if not cu.has("grants:read_resource"):
            raise HTTPException(403, "Missing permission: grants:read_resource")
        q = q.join(Resource, Resource.id == AccessGrant.resource_id).where(
            or_(Resource.owner_id == cu.id, Resource.backup_owner_id == cu.id))
    else:
        if not cu.has("grants:read_all"):
            raise HTTPException(403, "Missing permission: grants:read_all")
    if status and status != "ALL":
        q = q.where(AccessGrant.status == status)
    grants = db.execute(q.limit(500)).scalars().all()
    hints = {}
    if grants:
        for t in db.execute(select(AccessToken).where(AccessToken.grant_id.in_([g.id for g in grants]),
                                                      AccessToken.revoked_at.is_(None))).scalars():
            hints[t.grant_id] = t.token_hint
    return [{**grant_out(g, hints.get(g.id)), "can_manage": g.status == "ACTIVE" and _can_manage_grant(cu, g)} for g in grants]


@router.post("/grants/{grant_id}/token/reveal")
def reveal_token(grant_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only the grant holder can reveal their own purpose-bound token. Each reveal is audited."""
    g = db.get(AccessGrant, grant_id)
    if not g or g.user_id != cu.id:
        raise HTTPException(404, "Grant not found")
    t = db.execute(select(AccessToken).where(AccessToken.grant_id == g.id, AccessToken.revoked_at.is_(None))
                   .order_by(AccessToken.issued_at.desc())).scalars().first()
    if not t or g.status != "ACTIVE":
        raise HTTPException(410, "No active token for this grant")
    audit.record(db, cu.actor, "TOKEN_REVEALED", resource_id=g.resource_id, target_type="TOKEN", target_id=t.token_hint)
    db.commit()
    return {"token": crypto.decrypt(t.token_encrypted), "token_hint": t.token_hint, "purpose": t.purpose,
            "permissions": t.permissions, "expires_at": t.expires_at, "resource_id": t.resource_id,
            "request_id": t.request_id, "approval_ref": t.approval_ref}


def _can_manage_grant(cu: CurrentUser, g: AccessGrant) -> bool:
    """Who may revoke or narrow a grant (always enforced here, never only in the UI):
    the Security Manager (any grant), the resource owner, or the holder's reporting manager.
    Employees cannot change their own grants. Emergency grants follow the break-glass flow."""
    if cu.has("grants:revoke_any"):
        return True
    if cu.has("grants:revoke_own_resource") and cu.id in (g.resource.owner_id, g.resource.backup_owner_id):
        return True
    if g.is_emergency:
        return False
    return cu.has("grants:revoke_team") and g.user.manager_id == cu.id


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: str, body: ReasonIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(AccessGrant, grant_id)
    if not g:
        raise HTTPException(404, "Grant not found")
    if not _can_manage_grant(cu, g):
        raise HTTPException(403, "Only the employee's manager or the Security Manager can revoke this access.")
    if not grant_svc.revoke_grant(db, cu.actor, g, body.reason):
        raise HTTPException(409, "Grant is not active")
    db.commit()
    return grant_out(g)


class RestrictIn(BaseModel):
    permissions: list[str] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/grants/{grant_id}/restrict")
def restrict_grant(grant_id: str, body: RestrictIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(AccessGrant, grant_id)
    if not g or g.status != "ACTIVE":
        raise HTTPException(404, "Active grant not found")
    if not _can_manage_grant(cu, g):
        raise HTTPException(403, "Only the employee's manager or the Security Manager can change this access.")
    try:
        grant_svc.restrict_grant(db, cu.actor, g, body.permissions, body.reason)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return grant_out(g)


# ------------------------------------------------------------------ resources
@router.get("/resources")
def list_resources(cu: CurrentUser = Depends(require("resources:read")), db: Session = Depends(get_db)):
    from sqlalchemy import func

    counts = dict(db.execute(select(AccessGrant.resource_id, func.count()).where(AccessGrant.status == "ACTIVE")
                             .group_by(AccessGrant.resource_id)).all())
    rows = db.execute(select(Resource).order_by(Resource.code)).scalars().all()
    return [{**resource_full(r), "active_grants": counts.get(r.id, 0),
             "can_manage": cu.has("resources:manage_all") or (cu.has("resources:manage_own") and cu.id in (r.owner_id, r.backup_owner_id))}
            for r in rows]


@router.get("/resources/{resource_id}")
def get_resource(resource_id: str, cu: CurrentUser = Depends(require("resources:read")), db: Session = Depends(get_db)):
    r = db.get(Resource, resource_id)
    if not r:
        raise HTTPException(404, "Resource not found")
    out = resource_full(r)
    privileged = cu.has("grants:read_all") or cu.id in (r.owner_id, r.backup_owner_id)
    out["can_manage"] = cu.has("resources:manage_all") or (cu.has("resources:manage_own") and cu.id in (r.owner_id, r.backup_owner_id))
    from app.models import Policy, ResourceAccessEvent

    out["policies"] = [{"id": p.id, "name": p.name, "type": p.policy_type, "rules": p.rules, "enabled": p.enabled}
                       for p in db.execute(select(Policy).where(Policy.resource_id == r.id)).scalars()]
    if privileged:
        out["grants"] = [grant_out(g) for g in db.execute(select(AccessGrant).where(AccessGrant.resource_id == r.id)
                                                         .order_by(AccessGrant.granted_at.desc()).limit(100)).scalars()]
        names = dict(db.execute(select(User.id, User.full_name)).all())
        agents = dict(db.execute(select(AiAgent.id, AiAgent.name)).all())
        out["access_history"] = [
            {"at": e.occurred_at, "who": names.get(e.user_id) or agents.get(e.agent_id), "agent": bool(e.agent_id),
             "action": e.action, "purpose": e.purpose, "outcome": e.outcome, "reason": e.reason}
            for e in db.execute(select(ResourceAccessEvent).where(ResourceAccessEvent.resource_id == r.id)
                                .order_by(ResourceAccessEvent.occurred_at.desc()).limit(100)).scalars()]
    else:
        out["active_grants"] = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(AccessGrant)
                                         .where(AccessGrant.resource_id == r.id, AccessGrant.status == "ACTIVE"))
    return out


class ResourcePolicyIn(BaseModel):
    max_duration_hours: int | None = Field(default=None, ge=1, le=2160)
    allowed_purposes: list[str] | None = None
    allowed_departments: list[str] | None = None
    available_permissions: list[str] | None = None
    breakglass_allowed: bool | None = None
    requires_risk_review: bool | None = None
    backup_owner_id: str | None = None


@router.patch("/resources/{resource_id}")
def update_resource_policy(resource_id: str, body: ResourcePolicyIn, cu: CurrentUser = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    r = db.get(Resource, resource_id)
    if not r:
        raise HTTPException(404, "Resource not found")
    if not (cu.has("resources:manage_all") or (cu.has("resources:manage_own") and cu.id in (r.owner_id, r.backup_owner_id))):
        raise HTTPException(403, "Only the resource owner or a Security Admin can change resource policy.")
    changes = body.model_dump(exclude_none=True)
    if "allowed_purposes" in changes and any(p not in PURPOSES for p in changes["allowed_purposes"]):
        raise HTTPException(422, "Unknown purpose")
    if "available_permissions" in changes and any(p not in PERMISSIONS for p in changes["available_permissions"]):
        raise HTTPException(422, "Unknown permission")
    prev = {k: getattr(r, k) for k in changes}
    for k, v in changes.items():
        setattr(r, k, v)
    audit.record(db, cu.actor, "RESOURCE_POLICY_UPDATED", resource_id=r.id, target_type="RESOURCE", target_id=r.code,
                 previous_state=prev, new_state=changes)
    db.commit()
    return resource_full(r)


# ------------------------------------------------------------------ enforcement gateway
class GatewayIn(BaseModel):
    action: str = Field(pattern="^(READ|EXECUTE|WRITE|DELETE|ADMIN)$")
    purpose: str


@router.post("/gateway/resources/{resource_id}/access")
def gateway_access(resource_id: str, body: GatewayIn, x_access_token: str | None = Header(default=None),
                   cu: CurrentUser = Depends(require("gateway:use")), db: Session = Depends(get_db)):
    """Protected (simulated) resource endpoint. Validates the purpose-bound token on every call."""
    d = gateway.enforce_user_access(db, cu.actor, resource_id, x_access_token, body.action, body.purpose)
    db.commit()
    if not d.allowed:
        raise HTTPException(403, {"decision": "DENIED", "code": d.code, "message": d.reason})
    return {"decision": "ALLOWED", "code": d.code, "message": d.reason, "token": d.token_hint, "data": d.data}


class AgentInvokeIn(BaseModel):
    resource: str
    action: str = Field(pattern="^(READ|EXECUTE|WRITE|DELETE|ADMIN)$")
    tool: str = Field(min_length=1, max_length=64)


@router.post("/agent-gateway/invoke", tags=["ai-agents"])
def agent_invoke(body: AgentInvokeIn, x_agent_id: str = Header(), x_agent_key: str = Header(),
                 db: Session = Depends(get_db)):
    """Authorization gateway every AI agent call must pass through (agent credential auth)."""
    agent = gateway.authenticate_agent(db, x_agent_id, x_agent_key)
    if not agent:
        raise HTTPException(401, "Invalid agent credentials")
    d = gateway.enforce_agent_access(db, agent, body.resource, body.action, body.tool)
    db.commit()
    if not d.allowed:
        raise HTTPException(403, {"decision": "DENIED", "code": d.code, "message": d.reason})
    return {"decision": "ALLOWED", "code": d.code, "message": d.reason, "data": d.data}
