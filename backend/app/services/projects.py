"""Projects as the time box for access.

An employee's *current project* is the active project they belong to that ends soonest. Time-bound access granted
through a request is linked to that project and never outlives it: if the approved duration would run past the
project end date, the grant expires on the project end date instead. Example: the Fraud Detection Model is needed
for Project Falcon, Falcon ends on 15 Nov, so the grant also expires on 15 Nov.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccessGrant, Department, Project, ProjectMember, Task, User, utcnow


def current_project(db: Session, user_id: str, at: datetime | None = None) -> Project | None:
    at = at or utcnow()
    return db.execute(
        select(Project).join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id, Project.status == "ACTIVE", Project.end_date.is_not(None),
               Project.end_date > at)
        .order_by(Project.end_date, Project.name).limit(1)
    ).scalar_one_or_none()


def resolve_project(db: Session, user_id: str, project_id: str | None, at: datetime | None = None) -> Project | None:
    """The project a grant belongs to: the one recorded on the request if it is still running, else the current one."""
    at = at or utcnow()
    if project_id:
        p = db.get(Project, project_id)
        if p and p.status == "ACTIVE" and p.end_date and p.end_date > at:
            return p
    return current_project(db, user_id, at)


def cap_expiry(project: Project | None, expires_at: datetime | None) -> tuple[datetime | None, bool]:
    """Access must end on or before the project end date. Returns (expiry, capped)."""
    if project is None or project.end_date is None or expires_at is None:
        return expires_at, False
    if expires_at > project.end_date:
        return project.end_date, True
    return expires_at, False


def _iso(d: datetime | None):
    return d.isoformat() if d else None


def timeline(db: Session, user: User) -> dict:
    """Current project, its team, and every time-bound grant drawn on one timeline."""
    now = utcnow()
    p = current_project(db, user.id, now)
    standing_count = db.scalar(select(func.count()).select_from(AccessGrant).where(
        AccessGrant.user_id == user.id, AccessGrant.status == "ACTIVE", AccessGrant.expires_at.is_(None))) or 0
    if p is None:
        return {"project": None, "team": [], "grants": [], "standing_grants": standing_count, "now": now}

    members = db.execute(select(User, ProjectMember.role).join(ProjectMember, ProjectMember.user_id == User.id)
                         .where(ProjectMember.project_id == p.id).order_by(User.full_name)).all()
    my_role = next((role for u, role in members if u.id == user.id), None)
    tasks = db.execute(select(Task.status).where(Task.project_id == p.id, Task.assignee_id == user.id)).scalars().all()

    rows = db.execute(select(AccessGrant).where(
        AccessGrant.user_id == user.id, AccessGrant.expires_at.is_not(None),
        (AccessGrant.status == "ACTIVE") | (AccessGrant.granted_at >= p.start_date) | (AccessGrant.project_id == p.id),
    ).order_by(AccessGrant.granted_at.desc()).limit(12)).scalars().all()

    dept = db.get(Department, p.department_id) if p.department_id else None
    span = (p.end_date - p.start_date).total_seconds() if p.start_date else 0
    elapsed = (now - p.start_date).total_seconds() if p.start_date else 0
    return {
        "project": {
            "id": p.id, "code": p.code, "name": p.name, "description": p.description, "status": p.status,
            "team_name": p.team_name, "department": dept.name if dept else None,
            "start_date": p.start_date, "submission_date": p.submission_date, "end_date": p.end_date,
            "days_to_submission": (p.submission_date - now).days if p.submission_date else None,
            "days_to_end": (p.end_date - now).days,
            "progress": round(max(0.0, min(1.0, elapsed / span)), 3) if span > 0 else None,
            "my_role": my_role,
            "tasks": {"open": sum(1 for s in tasks if s != "DONE"), "done": sum(1 for s in tasks if s == "DONE")},
        },
        "manager": {"id": user.manager.id, "name": user.manager.full_name} if user.manager else None,
        "team": [{"id": u.id, "name": u.full_name, "designation": u.designation, "role": role, "is_me": u.id == user.id}
                 for u, role in members],
        "grants": [{
            "id": g.id, "resource": {"id": g.resource.id, "name": g.resource.name, "code": g.resource.code,
                                     "sensitivity": g.resource.sensitivity, "type": g.resource.resource_type},
            "permissions": g.permissions, "status": g.status, "source": g.source, "is_emergency": g.is_emergency,
            "granted_at": g.granted_at, "expires_at": g.expires_at,
            "ended_at": g.revoked_at if g.status != "ACTIVE" else None,
            "linked": g.project_id == p.id,
            "capped_to_project_end": g.project_id == p.id and g.expires_at == p.end_date,
            "within_project": g.expires_at <= p.end_date,
        } for g in rows],
        "standing_grants": standing_count,
        "now": now,
    }
