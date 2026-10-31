"""Employee intelligence, permission drift, break-glass, recertification and AI agents."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require, require_any
from app.api.serializers import agent_out, emergency_out, grant_out, resource_brief, user_brief
from app.core.catalog import sort_perms
from app.core.db import get_db
from app.models import (
    AccessGrant,
    AccessReview,
    AccessReviewCampaign,
    AgentPermission,
    AiAgent,
    Department,
    DriftFinding,
    EmergencySession,
    Project,
    ProjectMember,
    Resource,
    ResourceAccessEvent,
    SecurityAlert,
    Task,
    User,
    utcnow,
)
from app.security import crypto
from app.services import analytics, audit, breakglass, drift, gateway, recert
from app.services import grants as grant_svc
from app.services import projects as project_svc
from app.services import users as user_svc

router = APIRouter(prefix="/api", tags=["governance"])


# ------------------------------------------------------------------ employees
def _visible_user_ids(db: Session, cu: CurrentUser) -> list[str] | None:
    """None = all users. Managers see their reporting line (direct + indirect reports)."""
    if cu.has("employees:read_all"):
        return None
    if not cu.has("employees:read_team"):
        raise HTTPException(403, "Missing permission: employees:read_team")
    ids, frontier = [], [cu.id]
    while frontier:
        nxt = db.execute(select(User.id).where(User.manager_id.in_(frontier))).scalars().all()
        nxt = [i for i in nxt if i not in ids]
        ids += nxt
        frontier = nxt
    return ids


def _assert_visible(db: Session, cu: CurrentUser, user_id: str) -> User:
    ids = _visible_user_ids(db, cu)
    u = db.get(User, user_id)
    if not u or (ids is not None and user_id not in ids):
        raise HTTPException(404, "Employee not found")
    return u


@router.get("/departments")
def departments(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(User.department_id, func.count()).where(User.status == "ACTIVE")
                             .group_by(User.department_id)).all())
    return [{"id": d.id, "code": d.code, "name": d.name, "employees": counts.get(d.id, 0)}
            for d in db.execute(select(Department).order_by(Department.name)).scalars()]


@router.get("/projects")
def projects(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": p.id, "code": p.code, "name": p.name, "department_id": p.department_id, "status": p.status}
            for p in db.execute(select(Project).order_by(Project.name)).scalars()]


@router.get("/employees")
def list_employees(q: str | None = None, department_id: str | None = None, project_id: str | None = None,
                   status: str | None = None, cu: CurrentUser = Depends(require_any("employees:read_team", "employees:read_all")),
                   db: Session = Depends(get_db)):
    ids = _visible_user_ids(db, cu)
    stmt = select(User).where(User.is_service_account.is_(False)).order_by(User.full_name)
    if ids is not None:
        stmt = stmt.where(User.id.in_(ids))
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if status:
        stmt = stmt.where(User.status == status)
    if project_id:
        stmt = stmt.join(ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like),
                              func.lower(User.employee_id).like(like)))
    users = db.execute(stmt).scalars().unique().all()
    grants = dict(db.execute(select(AccessGrant.user_id, func.count()).where(AccessGrant.status == "ACTIVE")
                             .group_by(AccessGrant.user_id)).all())
    done = dict(db.execute(select(Task.assignee_id, func.count()).where(Task.status == "DONE", Task.verified_at.is_not(None))
                           .group_by(Task.assignee_id)).all())
    viol = dict(db.execute(select(SecurityAlert.user_id, func.count()).where(SecurityAlert.category.in_(
        ["POLICY_VIOLATION", "UNAUTHORIZED_ACCESS", "TOKEN_MISUSE", "SOD_VIOLATION", "BREAKGLASS_MISUSE"]))
        .group_by(SecurityAlert.user_id)).all())
    return [{**user_brief(u), "manager_id": u.manager_id, "joined_at": u.joined_at, "active_grants": grants.get(u.id, 0),
             "verified_tasks": done.get(u.id, 0), "violations": viol.get(u.id, 0)} for u in users]


@router.get("/employees/{user_id}")
def employee_profile(user_id: str, cu: CurrentUser = Depends(require_any("employees:read_team", "employees:read_all")),
                     db: Session = Depends(get_db)):
    u = _assert_visible(db, cu, user_id)
    projects = db.execute(select(Project, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id)
                          .where(ProjectMember.user_id == u.id)).all()
    grants = db.execute(select(AccessGrant).where(AccessGrant.user_id == u.id).order_by(AccessGrant.granted_at.desc())).scalars().all()
    tasks = db.execute(select(Task).where(Task.assignee_id == u.id).order_by(Task.created_at.desc())).scalars().all()
    pnames = {p.id: p.name for p, _ in projects}
    violations = db.execute(select(SecurityAlert).where(SecurityAlert.user_id == u.id).order_by(SecurityAlert.created_at.desc())
                            .limit(20)).scalars().all()
    return {
        **user_brief(u), "joined_at": u.joined_at, "location": u.location, "device_trust": u.device_trust,
        "manager": user_brief(u.manager) if u.manager else None,
        "projects": [{"id": p.id, "name": p.name, "code": p.code, "role": role} for p, role in projects],
        "current_permissions": [grant_out(g) for g in grants if g.status == "ACTIVE"],
        "access_history": [grant_out(g) for g in grants if g.status != "ACTIVE"][:30],
        "completed_tasks": [{"id": t.id, "code": t.code, "title": t.title, "project": pnames.get(t.project_id),
                             "completed_at": t.completed_at, "verified": t.verified_at is not None, "quality": t.quality_score}
                            for t in tasks if t.status == "DONE"][:25],
        "pending_tasks": [{"id": t.id, "code": t.code, "title": t.title, "project": pnames.get(t.project_id),
                           "status": t.status, "due_at": t.due_at} for t in tasks if t.status != "DONE"],
        "security_violations": [{"id": a.id, "severity": a.severity, "category": a.category, "title": a.title,
                                 "at": a.created_at} for a in violations],
        "work": analytics.work_stats(db, u.id), "activity_level_30d": analytics.activity_level(db, u),
        "can_manage": cu.has("users:manage"),
    }


@router.get("/employees/{user_id}/analytics")
def employee_analytics(user_id: str, cu: CurrentUser = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    _assert_visible(db, cu, user_id)
    return analytics.employee_charts(db, user_id)


@router.get("/employees/{user_id}/timeline")
def employee_timeline(user_id: str, cu: CurrentUser = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    _assert_visible(db, cu, user_id)
    return analytics.timeline(db, user_id)


@router.get("/me/project-timeline")
def my_project_timeline(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in employee's current project, its team, and their access on the project timeline."""
    return project_svc.timeline(db, db.get(User, cu.id))


@router.get("/employees/{user_id}/project-timeline")
def employee_project_timeline(user_id: str, cu: CurrentUser = Depends(require("analytics:read")),
                              db: Session = Depends(get_db)):
    return project_svc.timeline(db, _assert_visible(db, cu, user_id))


@router.get("/employees/{user_id}/evidence")
def employee_evidence(user_id: str, days: int = 90, cu: CurrentUser = Depends(require("analytics:read")),
                      db: Session = Depends(get_db)):
    _assert_visible(db, cu, user_id)
    return analytics.evidence(db, user_id, days)


@router.get("/leaderboard")
def leaderboard(department_id: str | None = None, project_id: str | None = None, days: int = Query(90, ge=7, le=365),
                cu: CurrentUser = Depends(require("leaderboard:read")), db: Session = Depends(get_db)):
    ids = _visible_user_ids(db, cu)
    return {"rows": analytics.leaderboard(db, ids, department_id, project_id, days),
            "methodology": {
                "weights": {"verified_task_completion": 35, "project_contribution": 15, "on_time_delivery": 20,
                            "quality_of_work": 20, "successful_authorized_operations": 10},
                "rules": ["Only verified, recorded task events count.",
                          "Number of access requests is never used.",
                          "Authorized operations are log-scaled and capped at 60 so heavy resource usage is not rewarded.",
                          "Scores are informational and never grant permissions.",
                          "Security risk is shown separately and does not affect this ranking."]}}


class DeactivateIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/employees/{user_id}/deactivate")
def deactivate(user_id: str, body: DeactivateIn, cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Employee not found")
    try:
        return user_svc.deactivate(db, cu.actor, u, body.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))


class TransferIn(BaseModel):
    department_id: str
    manager_id: str | None = None
    designation: str | None = None


@router.post("/employees/{user_id}/transfer")
def transfer(user_id: str, body: TransferIn, cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.status != "ACTIVE":
        raise HTTPException(404, "Employee not found")
    try:
        return user_svc.transfer(db, cu.actor, u, body.department_id, body.manager_id, body.designation)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ------------------------------------------------------------------ permission drift
def _drift_out(f: DriftFinding, users: dict, resources: dict) -> dict:
    return {"id": f.id, "user": user_brief(users.get(f.user_id)), "resource": resource_brief(resources.get(f.resource_id)),
            "baseline": f.baseline_permissions, "current": f.current_permissions, "excess": f.excess_permissions,
            "unused": f.unused_permissions, "issues": f.issues, "score": f.drift_score, "severity": f.severity,
            "recommendation": f.recommendation, "status": f.status, "detected_at": f.detected_at, "resolved_at": f.resolved_at}


@router.get("/drift")
def list_drift(status: str | None = "OPEN", cu: CurrentUser = Depends(require("drift:read")), db: Session = Depends(get_db)):
    q = select(DriftFinding).order_by(DriftFinding.drift_score.desc())
    if status and status != "ALL":
        q = q.where(DriftFinding.status == status)
    if not cu.has("grants:read_all") and not cu.has("employees:read_all"):
        scope = set()
        if cu.has("employees:read_team"):
            scope |= set(_visible_user_ids(db, cu) or [])
        owned = set(db.execute(select(Resource.id).where(or_(Resource.owner_id == cu.id, Resource.backup_owner_id == cu.id))).scalars())
        q = q.where(or_(DriftFinding.user_id.in_(scope or [""]), DriftFinding.resource_id.in_(owned or [""])))
    rows = db.execute(q).scalars().all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({r.user_id for r in rows} or [""]))).scalars()}
    res = {r.id: r for r in db.execute(select(Resource)).scalars()}
    summary = {k: sum(1 for r in rows if r.severity == k) for k in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}
    return {"findings": [_drift_out(f, users, res) for f in rows], "summary": summary}


@router.post("/drift/scan")
def drift_scan(cu: CurrentUser = Depends(require("drift:scan")), db: Session = Depends(get_db)):
    return drift.scan(db, cu.actor)


class DriftActionIn(BaseModel):
    action: str = Field(pattern="^(REVIEW|REVOKE|RESTRICT|SCHEDULE_REVIEW)$")
    permissions: list[str] | None = None  # for RESTRICT: permissions to keep
    comment: str | None = None


@router.post("/drift/{finding_id}/action")
def drift_action(finding_id: str, body: DriftActionIn, cu: CurrentUser = Depends(require("drift:read")),
                 db: Session = Depends(get_db)):
    f = db.get(DriftFinding, finding_id)
    if not f:
        raise HTTPException(404, "Finding not found")
    res = db.get(Resource, f.resource_id)
    is_owner = cu.id in (res.owner_id, res.backup_owner_id)
    is_admin = cu.has("grants:revoke_any")
    is_manager = db.get(User, f.user_id).manager_id == cu.id
    # Removing permissions needs an authorized approver (resource owner or Security Admin) - never automatic.
    if body.action in ("REVOKE", "RESTRICT") and not (is_admin or (is_owner and cu.has("drift:act"))):
        raise HTTPException(403, "Only the resource owner or a Security Admin can remove permissions.")
    if body.action in ("REVIEW", "SCHEDULE_REVIEW") and not (is_admin or is_owner or is_manager or cu.has("drift:act")):
        raise HTTPException(403, "Not authorized for this finding.")
    if f.user_id == cu.id:
        raise HTTPException(403, "You cannot action drift on your own access.")
    grants = db.execute(select(AccessGrant).where(AccessGrant.user_id == f.user_id, AccessGrant.resource_id == f.resource_id,
                                                  AccessGrant.status == "ACTIVE")).scalars().all()
    prev_status = f.status
    if body.action == "REVOKE":
        for g in grants:
            grant_svc.revoke_grant(db, cu.actor, g, f"Permission drift remediation. {body.comment or ''}".strip())
        f.status, f.resolved_at = "REMEDIATED", utcnow()
    elif body.action == "RESTRICT":
        keep = sort_perms(body.permissions or f.baseline_permissions or ["READ"])
        for g in grants:
            if set(g.permissions) - set(keep):
                if set(g.permissions) & set(keep):
                    grant_svc.restrict_grant(db, cu.actor, g, keep, "Permission drift remediation")
                else:
                    grant_svc.revoke_grant(db, cu.actor, g, "Permission drift remediation (no retained permissions)")
        f.status, f.resolved_at = "REMEDIATED", utcnow()
    elif body.action == "REVIEW":
        f.status = "REVIEWED"
    else:
        camp = AccessReviewCampaign(name=f"Drift review: {f.id[:8]}", due_at=utcnow() + timedelta(days=7), created_by_id=cu.id)
        db.add(camp)
        db.flush()
        reviewer = db.get(User, f.user_id).manager_id or res.owner_id
        for g in grants:
            db.add(AccessReview(campaign_id=camp.id, reviewer_id=reviewer, grant_id=g.id, user_id=f.user_id,
                                resource_id=f.resource_id, due_at=camp.due_at))
        f.status = "REVIEW_SCHEDULED"
    audit.record(db, cu.actor, f"DRIFT_{body.action}", resource_id=f.resource_id, target_type="DRIFT_FINDING", target_id=f.id,
                 previous_state={"status": prev_status, "permissions": f.current_permissions},
                 new_state={"status": f.status, "kept": body.permissions}, reason=body.comment)
    db.commit()
    return {"id": f.id, "status": f.status}


# ------------------------------------------------------------------ break-glass
class EmergencyIn(BaseModel):
    resource_id: str
    permissions: list[str] = Field(min_length=1)
    justification: str = Field(min_length=30, max_length=2000)
    incident_ref: str = Field(min_length=5, max_length=20)
    duration_minutes: int | None = Field(default=None, ge=5, le=240)


@router.post("/emergency", status_code=201)
def emergency_activate(body: EmergencyIn, cu: CurrentUser = Depends(require("emergency:request")), db: Session = Depends(get_db)):
    try:
        es, token = breakglass.activate(db, cu.actor, resource_id=body.resource_id, permissions=body.permissions,
                                        justification=body.justification, incident_ref=body.incident_ref,
                                        duration_minutes=body.duration_minutes)
    except breakglass.BreakGlassError as e:
        raise HTTPException(e.status, e.message)
    return {**emergency_out(es, 0), "token": token}


@router.get("/emergency")
def emergency_list(scope: str = Query("mine", pattern="^(mine|all)$"), cu: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    q = select(EmergencySession).order_by(EmergencySession.started_at.desc())
    if scope == "all":
        if not cu.has("emergency:monitor"):
            raise HTTPException(403, "Missing permission: emergency:monitor")
    else:
        q = q.where(EmergencySession.user_id == cu.id)
    rows = db.execute(q.limit(200)).scalars().all()
    counts = dict(db.execute(select(ResourceAccessEvent.emergency_session_id, func.count())
                             .where(ResourceAccessEvent.emergency_session_id.in_([r.id for r in rows] or [""]))
                             .group_by(ResourceAccessEvent.emergency_session_id)).all())
    eligible = [resource_brief(r) | {"available_permissions": [p for p in r.available_permissions if p != "ADMIN"]}
                for r in db.execute(select(Resource).where(Resource.breakglass_allowed.is_(True))).scalars()]
    return {"sessions": [emergency_out(r, counts.get(r.id, 0)) for r in rows], "eligible_resources": eligible,
            "user_eligible": (cu.user.department.code if cu.user.department else None) in breakglass.ELIGIBLE_DEPARTMENTS}


@router.get("/emergency/{session_id}/actions")
def emergency_actions(session_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    es = db.get(EmergencySession, session_id)
    if not es or not (cu.has("emergency:monitor") or es.user_id == cu.id):
        raise HTTPException(404, "Session not found")
    return [{"at": e.occurred_at, "action": e.action, "outcome": e.outcome, "reason": e.reason, "ip": e.ip}
            for e in db.execute(select(ResourceAccessEvent).where(ResourceAccessEvent.emergency_session_id == es.id)
                                .order_by(ResourceAccessEvent.occurred_at.desc())).scalars()]


class EmergencyRevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/emergency/{session_id}/revoke")
def emergency_revoke(session_id: str, body: EmergencyRevokeIn, cu: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    try:
        return emergency_out(breakglass.revoke(db, cu.actor, session_id, body.reason))
    except breakglass.BreakGlassError as e:
        raise HTTPException(e.status, e.message)


class EmergencyReviewIn(BaseModel):
    outcome: str = Field(pattern="^(JUSTIFIED|MISUSE|INCONCLUSIVE)$")
    notes: str = Field(min_length=10, max_length=2000)


@router.post("/emergency/{session_id}/review")
def emergency_review(session_id: str, body: EmergencyReviewIn, cu: CurrentUser = Depends(require("emergency:review")),
                     db: Session = Depends(get_db)):
    try:
        return emergency_out(breakglass.review(db, cu.actor, session_id, body.outcome, body.notes))
    except breakglass.BreakGlassError as e:
        raise HTTPException(e.status, e.message)


# ------------------------------------------------------------------ recertification
def _review_out(r: AccessReview, users: dict, res: dict, grants: dict) -> dict:
    g = grants.get(r.grant_id)
    return {"id": r.id, "campaign_id": r.campaign_id, "reviewer": user_brief(users.get(r.reviewer_id)),
            "user": user_brief(users.get(r.user_id)), "resource": resource_brief(res.get(r.resource_id)),
            "permissions": g.permissions if g else [], "grant_status": g.status if g else None,
            "granted_at": g.granted_at if g else None, "expires_at": g.expires_at if g else None,
            "last_used_at": g.last_used_at if g else None, "unused": r.unused, "status": r.status, "due_at": r.due_at,
            "overdue": r.status == "PENDING" and r.due_at < utcnow(), "decided_at": r.decided_at, "comment": r.comment}


@router.get("/reviews")
def list_reviews(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                 cu: CurrentUser = Depends(require("reviews:read")), db: Session = Depends(get_db)):
    q = select(AccessReview).order_by(AccessReview.due_at)
    if scope == "mine" or not cu.has("users:manage"):
        q = q.where(AccessReview.reviewer_id == cu.id)
    if status:
        q = q.where(AccessReview.status == status)
    rows = db.execute(q.limit(500)).scalars().all()
    uids = {r.user_id for r in rows} | {r.reviewer_id for r in rows}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(uids or [""]))).scalars()}
    res = {r.id: r for r in db.execute(select(Resource)).scalars()}
    grants = {g.id: g for g in db.execute(select(AccessGrant).where(AccessGrant.id.in_({r.grant_id for r in rows} or [""]))).scalars()}
    camps = db.execute(select(AccessReviewCampaign).order_by(AccessReviewCampaign.started_at.desc()).limit(10)).scalars().all()
    return {"reviews": [_review_out(r, users, res, grants) for r in rows],
            "campaigns": [{"id": c.id, "name": c.name, "started_at": c.started_at, "due_at": c.due_at, "status": c.status}
                          for c in camps]}


class CampaignIn(BaseModel):
    name: str | None = None


@router.post("/reviews/campaigns", status_code=201)
def start_campaign(body: CampaignIn, cu: CurrentUser = Depends(require("reviews:initiate")), db: Session = Depends(get_db)):
    scope = None if cu.has("users:manage") else cu.id  # managers can only initiate reviews for their own team
    camp = recert.start_campaign(db, cu.actor, body.name, reviewer_scope=scope)
    n = db.scalar(select(func.count()).select_from(AccessReview).where(AccessReview.campaign_id == camp.id))
    return {"id": camp.id, "name": camp.name, "due_at": camp.due_at, "items": n}


@router.post("/reviews/process-overdue")
def process_overdue(cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    return {"overdue_flagged": recert.process_overdue(db)}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(RETAIN|RESTRICT|REVOKE)$")
    comment: str | None = None
    permissions: list[str] | None = None


@router.post("/reviews/{review_id}/decide")
def decide(review_id: str, body: DecisionIn, cu: CurrentUser = Depends(require("reviews:act")), db: Session = Depends(get_db)):
    try:
        r = recert.decide(db, cu.actor, review_id, body.decision, body.comment, body.permissions)
    except recert.ReviewError as e:
        raise HTTPException(e.status, e.message)
    return {"id": r.id, "status": r.status}


# ------------------------------------------------------------------ AI agents
@router.get("/agents")
def list_agents(cu: CurrentUser = Depends(require("agents:read")), db: Session = Depends(get_db)):
    res = {r.id: r for r in db.execute(select(Resource)).scalars()}
    agents = db.execute(select(AiAgent).order_by(AiAgent.name)).scalars().all()
    since = utcnow() - timedelta(days=7)
    stats = db.execute(select(ResourceAccessEvent.agent_id, ResourceAccessEvent.outcome, func.count())
                       .where(ResourceAccessEvent.agent_id.is_not(None), ResourceAccessEvent.occurred_at >= since)
                       .group_by(ResourceAccessEvent.agent_id, ResourceAccessEvent.outcome)).all()
    s: dict = {}
    for aid, outcome, n in stats:
        s.setdefault(aid, {"ALLOWED": 0, "DENIED": 0})[outcome] = n
    events = db.execute(select(ResourceAccessEvent).where(ResourceAccessEvent.agent_id.is_not(None))
                        .order_by(ResourceAccessEvent.occurred_at.desc()).limit(40)).scalars().all()
    names = {a.id: a.name for a in agents}
    return {"agents": [agent_out(a, res) | {"stats_7d": s.get(a.id, {"ALLOWED": 0, "DENIED": 0})} for a in agents],
            "recent_events": [{"at": e.occurred_at, "agent": names.get(e.agent_id), "resource": res[e.resource_id].name if e.resource_id in res else None,
                               "action": e.action, "tool": e.tool, "outcome": e.outcome, "reason": e.reason} for e in events],
            "resources": [resource_brief(r) for r in res.values()]}


class SimulateIn(BaseModel):
    resource_id: str
    action: str = Field(pattern="^(READ|EXECUTE|WRITE|DELETE|ADMIN)$")
    tool: str


@router.post("/agents/{agent_id}/simulate")
def simulate_agent(agent_id: str, body: SimulateIn, cu: CurrentUser = Depends(require("agents:read")),
                   db: Session = Depends(get_db)):
    """Test harness: runs an agent action through the same gateway policy as a real agent call.
    (The harness acts as the agent's runtime; real agents authenticate with X-Agent-Id / X-Agent-Key.)"""
    agent = db.get(AiAgent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    d = gateway.enforce_agent_access(db, agent, body.resource_id, body.action, body.tool, cu.actor.ip)
    audit.record(db, cu.actor, "AGENT_SIMULATION_RUN", resource_id=body.resource_id, target_type="AGENT", target_id=agent.code,
                 new_state={"action": body.action, "tool": body.tool, "decision": "ALLOWED" if d.allowed else "DENIED"})
    db.commit()
    return {"decision": "ALLOWED" if d.allowed else "DENIED", "code": d.code, "message": d.reason, "data": d.data}


class AgentStatusIn(BaseModel):
    status: str = Field(pattern="^(ACTIVE|SUSPENDED)$")
    reason: str = Field(min_length=3)


@router.post("/agents/{agent_id}/status")
def agent_status(agent_id: str, body: AgentStatusIn, cu: CurrentUser = Depends(require("agents:manage")),
                 db: Session = Depends(get_db)):
    a = db.get(AiAgent, agent_id)
    if not a:
        raise HTTPException(404, "Agent not found")
    prev = a.status
    a.status = body.status
    audit.record(db, cu.actor, "AGENT_STATUS_CHANGED", target_type="AGENT", target_id=a.code,
                 previous_state={"status": prev}, new_state={"status": a.status}, reason=body.reason)
    db.commit()
    return {"id": a.id, "status": a.status}


class AgentPermIn(BaseModel):
    resource_id: str
    permissions: list[str]
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


@router.put("/agents/{agent_id}/permissions")
def agent_set_permission(agent_id: str, body: AgentPermIn, cu: CurrentUser = Depends(require("agents:manage")),
                         db: Session = Depends(get_db)):
    a = db.get(AiAgent, agent_id)
    res = db.get(Resource, body.resource_id)
    if not a or not res:
        raise HTTPException(404, "Not found")
    if "ADMIN" in body.permissions:
        raise HTTPException(422, "AI agents can never hold ADMIN permissions.")
    if any(p not in res.available_permissions for p in body.permissions):
        raise HTTPException(422, "Permission not available on resource")
    p = db.execute(select(AgentPermission).where(AgentPermission.agent_id == a.id, AgentPermission.resource_id == res.id)).scalar_one_or_none()
    prev = p.permissions if p else None
    if not body.permissions:
        if p:
            db.delete(p)
    else:
        if not p:
            p = AgentPermission(agent_id=a.id, resource_id=res.id, permissions=[])
            db.add(p)
        p.permissions = sort_perms(body.permissions)
        p.revoked_at = None  # re-granting after a dependency-graph revocation
        p.revoked_by_id = None
        p.expires_at = utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    audit.record(db, cu.actor, "AGENT_PERMISSION_CHANGED", resource_id=res.id, target_type="AGENT", target_id=a.code,
                 previous_state={"permissions": prev}, new_state={"permissions": body.permissions})
    db.commit()
    return {"ok": True}


@router.post("/agents/{agent_id}/rotate-key")
def rotate_agent_key(agent_id: str, cu: CurrentUser = Depends(require("agents:manage")), db: Session = Depends(get_db)):
    a = db.get(AiAgent, agent_id)
    if not a:
        raise HTTPException(404, "Agent not found")
    key = "agk_" + crypto.random_token(32)
    a.api_key_hash = crypto.token_digest(key)
    audit.record(db, cu.actor, "AGENT_KEY_ROTATED", target_type="AGENT", target_id=a.code)
    db.commit()
    return {"agent_id": a.id, "api_key": key, "note": "Shown once. Store it in the agent's secret manager."}
