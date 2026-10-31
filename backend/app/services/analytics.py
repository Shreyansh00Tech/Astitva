"""Employee intelligence and executive dashboard analytics.

Work analytics are computed exclusively from recorded task events (TaskEvent / Task) and
gateway decisions (ResourceAccessEvent). Performance and security risk are kept separate,
and productivity never feeds into authorization decisions.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    AccessGrant,
    AccessRequest,
    AuditEvent,
    Department,
    DriftFinding,
    EmergencySession,
    Project,
    ProjectMember,
    Resource,
    ResourceAccessEvent,
    RiskAssessment,
    SecurityAlert,
    Task,
    TaskEvent,
    User,
    utcnow,
)


def _day(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _week(d: datetime) -> str:
    monday = (d - timedelta(days=d.weekday())).date()
    return monday.isoformat()


def _days(n: int) -> list[str]:
    today = utcnow().date()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _weeks(n: int) -> list[str]:
    today = utcnow()
    return [_week(today - timedelta(weeks=i)) for i in range(n - 1, -1, -1)]


def _months(n: int) -> list[str]:
    d = utcnow().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out[::-1]


# ------------------------------------------------------------------ employee
def work_stats(db: Session, user_id: str, since: datetime | None = None) -> dict:
    tq = select(Task).where(Task.assignee_id == user_id)
    tasks = db.execute(tq).scalars().all()
    done = [t for t in tasks if t.status == "DONE" and (since is None or (t.completed_at and t.completed_at >= since))]
    verified = [t for t in done if t.verified_at is not None]
    on_time = [t for t in verified if t.due_at and t.completed_at and t.completed_at <= t.due_at]
    quality = [t.quality_score for t in verified if t.quality_score is not None]
    ops_q = select(func.count()).select_from(ResourceAccessEvent).where(ResourceAccessEvent.user_id == user_id,
                                                                       ResourceAccessEvent.outcome == "ALLOWED")
    den_q = select(func.count()).select_from(ResourceAccessEvent).where(ResourceAccessEvent.user_id == user_id,
                                                                       ResourceAccessEvent.outcome == "DENIED")
    if since:
        ops_q = ops_q.where(ResourceAccessEvent.occurred_at >= since)
        den_q = den_q.where(ResourceAccessEvent.occurred_at >= since)
    projects = {t.project_id for t in verified}
    return {
        "completed_tasks": len(done), "verified_tasks": len(verified),
        "pending_tasks": sum(1 for t in tasks if t.status != "DONE"),
        "on_time_rate": round(len(on_time) / len(verified), 3) if verified else 0.0,
        "avg_quality": round(sum(quality) / len(quality), 2) if quality else 0.0,
        "projects_contributed": len(projects),
        "successful_operations": db.scalar(ops_q) or 0, "denied_operations": db.scalar(den_q) or 0,
    }


def activity_level(db: Session, user: User) -> str:
    since = utcnow() - timedelta(days=30)
    mine = db.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.user_id == user.id,
                                                                      TaskEvent.occurred_at >= since)) or 0
    dept_counts = db.execute(select(TaskEvent.user_id, func.count()).select_from(TaskEvent).join(User, User.id == TaskEvent.user_id)
                             .where(User.department_id == user.department_id, TaskEvent.occurred_at >= since)
                             .group_by(TaskEvent.user_id)).all()
    vals = sorted(c for _, c in dept_counts) or [0]
    median = vals[len(vals) // 2]
    if mine >= max(1, median * 1.2):
        return "High"
    if mine >= median * 0.6:
        return "Medium"
    return "Low"


def employee_charts(db: Session, user_id: str) -> dict:
    now = utcnow()
    events = db.execute(select(TaskEvent).where(TaskEvent.user_id == user_id,
                                                TaskEvent.occurred_at >= now - timedelta(days=182))).scalars().all()
    tasks = db.execute(select(Task).where(Task.assignee_id == user_id)).scalars().all()
    access = db.execute(select(ResourceAccessEvent).where(ResourceAccessEvent.user_id == user_id,
                                                          ResourceAccessEvent.occurred_at >= now - timedelta(days=182))
                        ).scalars().all()
    reqs = db.execute(select(AccessRequest).where(AccessRequest.requester_id == user_id)).scalars().all()

    daily = Counter(_day(e.occurred_at) for e in events if e.occurred_at >= now - timedelta(days=30))
    weekly_done = Counter(_week(t.completed_at) for t in tasks if t.completed_at and t.verified_at)
    weekly_events = Counter(_week(e.occurred_at) for e in events)
    month_done = Counter(t.completed_at.strftime("%Y-%m") for t in tasks if t.completed_at)
    month_assigned = Counter(t.created_at.strftime("%Y-%m") for t in tasks)
    proj_names = dict(db.execute(select(Project.id, Project.name)).all())
    proj = Counter(proj_names.get(t.project_id, "?") for t in tasks if t.status == "DONE" and t.verified_at)
    res_names = dict(db.execute(select(Resource.id, Resource.name)).all())
    util = Counter(res_names.get(a.resource_id, "?") for a in access if a.outcome == "ALLOWED")
    perm_use = Counter(a.action for a in access if a.outcome == "ALLOWED")
    sd = defaultdict(lambda: {"allowed": 0, "denied": 0})
    for a in access:
        sd[_week(a.occurred_at)]["allowed" if a.outcome == "ALLOWED" else "denied"] += 1
    req_hist = defaultdict(lambda: {"approved": 0, "rejected": 0, "pending": 0})
    for r in reqs:
        k = r.created_at.strftime("%Y-%m")
        bucket = "approved" if r.status == "APPROVED" else "rejected" if r.status == "REJECTED" else "pending"
        req_hist[k][bucket] += 1

    return {
        "daily_activity": [{"date": d, "events": daily.get(d, 0)} for d in _days(30)],
        "weekly_productivity": [{"week": w, "completed": weekly_done.get(w, 0), "events": weekly_events.get(w, 0)}
                                for w in _weeks(12)],
        "monthly_completion": [{"month": m, "completed": month_done.get(m, 0), "assigned": month_assigned.get(m, 0)}
                               for m in _months(6)],
        "project_contribution": [{"project": k, "tasks": v} for k, v in proj.most_common()],
        "resource_utilization": [{"resource": k, "operations": v} for k, v in util.most_common()],
        "access_request_history": [{"month": m, **req_hist[m]} for m in _months(6)],
        "permission_usage": [{"permission": k, "count": v} for k, v in perm_use.most_common()],
        "access_outcomes": [{"week": w, **sd[w]} for w in _weeks(12)],
    }


def timeline(db: Session, user_id: str, limit: int = 60) -> list[dict]:
    proj_names = dict(db.execute(select(Project.id, Project.name)).all())
    res_names = dict(db.execute(select(Resource.id, Resource.name)).all())
    task_titles = dict(db.execute(select(Task.id, Task.title).where(Task.assignee_id == user_id)).all())
    rows = []
    for e in db.execute(select(TaskEvent).where(TaskEvent.user_id == user_id).order_by(TaskEvent.occurred_at.desc())
                        .limit(limit)).scalars():
        rows.append({"at": e.occurred_at, "kind": "TASK", "project": proj_names.get(e.project_id),
                     "task": task_titles.get(e.task_id), "resource": res_names.get(e.resource_id) if e.resource_id else None,
                     "action": e.action or e.event_type, "outcome": e.outcome or ("VERIFIED" if e.event_type == "VERIFIED" else "OK"),
                     "event_id": e.id})
    for a in db.execute(select(ResourceAccessEvent).where(ResourceAccessEvent.user_id == user_id)
                        .order_by(ResourceAccessEvent.occurred_at.desc()).limit(limit // 2)).scalars():
        rows.append({"at": a.occurred_at, "kind": "ACCESS", "project": None, "task": a.purpose and a.purpose.replace("_", " ").title(),
                     "resource": res_names.get(a.resource_id), "action": a.action, "outcome": a.outcome,
                     "event_id": a.id, "reason": a.reason})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:limit]


def leaderboard(db: Session, user_ids: list[str] | None = None, department_id: str | None = None,
                project_id: str | None = None, days: int = 90) -> list[dict]:
    """Ranks on verified work only. Request counts and raw resource volume are deliberately excluded;
    successful operations are log-scaled and capped so heavy usage is not rewarded."""
    since = utcnow() - timedelta(days=days)
    uq = select(User).where(User.status == "ACTIVE", User.is_service_account.is_(False))
    if user_ids is not None:
        uq = uq.where(User.id.in_(user_ids))
    if department_id:
        uq = uq.where(User.department_id == department_id)
    if project_id:
        uq = uq.join(ProjectMember, and_(ProjectMember.user_id == User.id, ProjectMember.project_id == project_id))
    users = db.execute(uq).scalars().unique().all()
    if not users:
        return []
    ids = [u.id for u in users]
    tq = select(Task).where(Task.assignee_id.in_(ids), Task.status == "DONE", Task.verified_at.is_not(None),
                            Task.completed_at >= since)
    if project_id:
        tq = tq.where(Task.project_id == project_id)
    tasks = db.execute(tq).scalars().all()
    by_user: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        by_user[t.assignee_id].append(t)
    ops = dict(db.execute(select(ResourceAccessEvent.user_id, func.count()).where(
        ResourceAccessEvent.user_id.in_(ids), ResourceAccessEvent.outcome == "ALLOWED",
        ResourceAccessEvent.occurred_at >= since).group_by(ResourceAccessEvent.user_id)).all())
    weight = {"LOW": 1, "MEDIUM": 1.5, "HIGH": 2, "CRITICAL": 2.5}
    max_done = max([sum(weight.get(t.priority, 1) for t in by_user[i]) for i in ids] + [1])
    OPS_CAP = 60
    rows = []
    for u in users:
        ts = by_user[u.id]
        weighted = sum(weight.get(t.priority, 1) for t in ts)
        on_time = [t for t in ts if t.due_at and t.completed_at <= t.due_at]
        q = [t.quality_score for t in ts if t.quality_score is not None]
        projects = Counter(t.project_id for t in ts)
        c_tasks = weighted / max_done
        c_proj = min(1.0, len(projects) / 3)
        c_time = len(on_time) / len(ts) if ts else 0
        c_quality = (sum(q) / len(q) / 5) if q else 0
        n_ops = min(ops.get(u.id, 0), OPS_CAP)
        c_ops = math.log1p(n_ops) / math.log1p(OPS_CAP)
        score = round(100 * (0.35 * c_tasks + 0.15 * c_proj + 0.20 * c_time + 0.20 * c_quality + 0.10 * c_ops), 1)
        rows.append({
            "user_id": u.id, "name": u.full_name, "employee_id": u.employee_id, "designation": u.designation,
            "department": u.department.name if u.department else None, "score": score,
            "verified_tasks": len(ts), "on_time_rate": round(c_time, 3), "avg_quality": round(sum(q) / len(q), 2) if q else 0,
            "projects": len(projects), "successful_operations": ops.get(u.id, 0),
            "breakdown": {"task_completion": round(35 * c_tasks, 1), "project_contribution": round(15 * c_proj, 1),
                          "on_time_delivery": round(20 * c_time, 1), "quality": round(20 * c_quality, 1),
                          "authorized_operations": round(10 * c_ops, 1)},
        })
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def evidence(db: Session, user_id: str, days: int = 90) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    proj = dict(db.execute(select(Project.id, Project.name)).all())
    verifier = dict(db.execute(select(User.id, User.full_name)).all())
    rows = db.execute(select(Task).where(Task.assignee_id == user_id, Task.status == "DONE",
                                         Task.completed_at >= since).order_by(Task.completed_at.desc())).scalars().all()
    return [{"task_id": t.id, "code": t.code, "title": t.title, "project": proj.get(t.project_id), "priority": t.priority,
             "due_at": t.due_at, "completed_at": t.completed_at, "on_time": bool(t.due_at and t.completed_at <= t.due_at),
             "quality_score": t.quality_score, "verified": t.verified_at is not None,
             "verified_by": verifier.get(t.verified_by_id)} for t in rows]


# ------------------------------------------------------------------ dashboard
def dashboard(db: Session) -> dict:
    now = utcnow()
    soon = now + timedelta(hours=72)
    metrics = {
        "total_employees": db.scalar(select(func.count()).select_from(User).where(User.status == "ACTIVE",
                                                                                  User.is_service_account.is_(False))),
        "active_grants": db.scalar(select(func.count()).select_from(AccessGrant).where(AccessGrant.status == "ACTIVE")),
        "pending_requests": db.scalar(select(func.count()).select_from(AccessRequest).where(AccessRequest.status == "PENDING")),
        "high_risk_requests": db.scalar(select(func.count()).select_from(AccessRequest)
                                        .join(RiskAssessment, RiskAssessment.request_id == AccessRequest.id)
                                        .where(AccessRequest.status == "PENDING", RiskAssessment.score > 60)),
        "expiring_permissions": db.scalar(select(func.count()).select_from(AccessGrant).where(
            AccessGrant.status == "ACTIVE", AccessGrant.expires_at.is_not(None), AccessGrant.expires_at <= soon)),
        "active_emergency_sessions": db.scalar(select(func.count()).select_from(EmergencySession)
                                               .where(EmergencySession.status == "ACTIVE")),
        "drift_alerts": db.scalar(select(func.count()).select_from(DriftFinding).where(DriftFinding.status == "OPEN")),
        "policy_violations": db.scalar(select(func.count()).select_from(SecurityAlert).where(
            SecurityAlert.status != "RESOLVED", SecurityAlert.created_at >= now - timedelta(days=30),
            SecurityAlert.category.in_(["POLICY_VIOLATION", "SOD_VIOLATION", "UNAUTHORIZED_ACCESS", "AGENT_UNAUTHORIZED",
                                        "TOKEN_MISUSE", "BREAKGLASS_MISUSE"]))),
    }
    reqs = db.execute(select(AccessRequest.created_at, AccessRequest.status, AccessRequest.decided_at)
                      .where(AccessRequest.created_at >= now - timedelta(days=84))).all()
    per_day = Counter(_day(c) for c, _, _ in reqs if c >= now - timedelta(days=30))
    trend = defaultdict(lambda: {"approved": 0, "rejected": 0})
    for c, st, dec in reqs:
        if st in ("APPROVED", "REJECTED"):
            trend[_week(dec or c)][st.lower()] += 1
    dept_names = dict(db.execute(select(Department.id, Department.name)).all())
    dept_usage = Counter()
    for dept_id, n in db.execute(select(User.department_id, func.count()).select_from(ResourceAccessEvent)
                                 .join(User, User.id == ResourceAccessEvent.user_id)
                                 .where(ResourceAccessEvent.outcome == "ALLOWED",
                                        ResourceAccessEvent.occurred_at >= now - timedelta(days=30))
                                 .group_by(User.department_id)).all():
        dept_usage[dept_names.get(dept_id, "Unassigned")] += n
    act = Counter(_week(t) for (t,) in db.execute(select(TaskEvent.occurred_at)
                                                  .where(TaskEvent.occurred_at >= now - timedelta(weeks=12))).all())
    risk_dist = Counter(lvl for (lvl,) in db.execute(select(RiskAssessment.level)
                                                     .where(RiskAssessment.created_at >= now - timedelta(days=90))).all())
    drift_tr = defaultdict(lambda: Counter())
    for d, sev in db.execute(select(DriftFinding.detected_at, DriftFinding.severity)
                             .where(DriftFinding.detected_at >= now - timedelta(weeks=12))).all():
        drift_tr[_week(d)][sev] += 1
    em = Counter(_week(s) for (s,) in db.execute(select(EmergencySession.started_at)
                                                 .where(EmergencySession.started_at >= now - timedelta(weeks=12))).all())
    exp = Counter(_day(e) for (e,) in db.execute(select(AccessGrant.expires_at).where(
        AccessGrant.status == "ACTIVE", AccessGrant.expires_at.is_not(None),
        AccessGrant.expires_at <= now + timedelta(days=14))).all())
    return {
        "metrics": metrics,
        "charts": {
            "requests_over_time": [{"date": d, "requests": per_day.get(d, 0)} for d in _days(30)],
            "approval_trends": [{"week": w, **trend[w]} for w in _weeks(12)],
            "department_usage": [{"department": k, "operations": v} for k, v in dept_usage.most_common()],
            "activity_trends": [{"week": w, "events": act.get(w, 0)} for w in _weeks(12)],
            "risk_distribution": [{"level": k, "count": risk_dist.get(k, 0)} for k in ("LOW", "MEDIUM", "HIGH", "CRITICAL")],
            "drift_trends": [{"week": w, **{k: drift_tr[w].get(k, 0) for k in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}}
                             for w in _weeks(12)],
            "emergency_history": [{"week": w, "sessions": em.get(w, 0)} for w in _weeks(12)],
            "expiry_timeline": [{"date": (now.date() + timedelta(days=i)).isoformat(),
                                 "expiring": exp.get((now.date() + timedelta(days=i)).isoformat(), 0)} for i in range(14)],
        },
        "recent_activity": recent_activity(db),
    }


ACTIVITY_TEMPLATES = {
    "REQUEST_CREATED": "{actor} requested access to {resource}",
    "REQUEST_APPROVE": "{actor} approved {target}",
    "REQUEST_NARROW_SCOPE": "{actor} narrowed the scope of {target}",
    "REQUEST_REJECT": "{actor} rejected {target}",
    "REQUEST_REQUEST_MODIFICATION": "{actor} requested changes on {target}",
    "RISK_ASSESSED": "Risk Engine scored {target}",
    "GRANT_ACTIVATED": "Access to {resource} became active",
    "GRANT_EXPIRED": "An expired grant on {resource} was revoked",
    "GRANT_REVOKED": "{actor} revoked access to {resource}",
    "GRANT_RESTRICTED": "{actor} restricted permissions on {resource}",
    "BREAKGLASS_ACTIVATED": "Emergency access activated on {resource}",
    "BREAKGLASS_REVOKED": "{actor} revoked an emergency session",
    "DRIFT_SCAN": "Security Engine scanned for permission drift",
    "SOD_VIOLATION_BLOCKED": "Separation-of-duties blocked {actor} on {target}",
    "AGENT_ACCESS_DENIED": "{actor} was denied access to {resource}",
    "RESOURCE_ACCESS_DENIED": "{actor} was denied access to {resource}",
    "USER_DEACTIVATED": "{actor} deactivated an employee",
    "RECERT_CAMPAIGN_STARTED": "Access recertification campaign started",
}


def recent_activity(db: Session, limit: int = 15) -> list[dict]:
    res_names = dict(db.execute(select(Resource.id, Resource.name)).all())
    rows = db.execute(select(AuditEvent).where(AuditEvent.action.in_(list(ACTIVITY_TEMPLATES)))
                      .order_by(AuditEvent.seq.desc()).limit(limit)).scalars().all()
    out = []
    for e in rows:
        text = ACTIVITY_TEMPLATES[e.action].format(actor=e.actor_name, resource=res_names.get(e.resource_id, "a resource"),
                                                   target=e.target_id or "a request")
        out.append({"seq": e.seq, "at": e.occurred_at, "text": text, "action": e.action, "actor_type": e.actor_type})
    return out
