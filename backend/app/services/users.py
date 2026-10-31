"""Joiner-mover-leaver lifecycle controls."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.models import AccessGrant, AccessRequest, AccessReview, AccessReviewCampaign, Department, EmergencySession, User, utcnow
from app.services import audit
from app.services.auth import revoke_all_sessions
from app.services.grants import revoke_grant
from app.services.notify import notify, raise_alert


def deactivate(db: Session, actor: Actor, user: User, reason: str) -> dict:
    """Leaver: revoke every active grant, token, session and emergency session immediately."""
    if user.id == actor.user.id:
        raise ValueError("You cannot deactivate your own account.")
    if user.status == "DEACTIVATED":
        raise ValueError("User already deactivated.")
    prev = {"status": user.status}
    user.status = "DEACTIVATED"
    user.deactivated_at = utcnow()
    grants = db.execute(select(AccessGrant).where(AccessGrant.user_id == user.id, AccessGrant.status == "ACTIVE")).scalars().all()
    for g in grants:
        revoke_grant(db, actor, g, f"Employee deactivated: {reason}")
    sessions = revoke_all_sessions(db, user.id, "ACCOUNT_DEACTIVATED")
    for es in db.execute(select(EmergencySession).where(EmergencySession.user_id == user.id,
                                                        EmergencySession.status == "ACTIVE")).scalars():
        es.status, es.ended_at, es.revoked_by_id = "REVOKED", utcnow(), actor.user.id
    cancelled = 0
    for r in db.execute(select(AccessRequest).where(AccessRequest.requester_id == user.id,
                                                    AccessRequest.status.in_(["PENDING", "CHANGES_REQUESTED"]))).scalars():
        r.status, r.current_stage = "CANCELLED", None
        cancelled += 1
    result = {"grants_revoked": len(grants), "sessions_revoked": sessions, "requests_cancelled": cancelled}
    audit.record(db, actor, "USER_DEACTIVATED", target_type="USER", target_id=user.id, previous_state=prev,
                 new_state={"status": "DEACTIVATED", **result}, reason=reason)
    raise_alert(db, "LOW", "LEAVER_PROCESSED", f"Leaver processed: {user.full_name}",
                f"{len(grants)} grants and {sessions} sessions revoked immediately.", user_id=user.id, notify_admins=False)
    if user.manager_id:
        notify(db, user.manager_id, "SECURITY", f"{user.full_name} deactivated",
               f"All access was revoked ({len(grants)} grants, {sessions} sessions).", f"/employees/{user.id}")
    db.commit()
    return result


def transfer(db: Session, actor: Actor, user: User, department_id: str, manager_id: str | None, designation: str | None) -> dict:
    """Mover: department change triggers immediate recertification of all carried-over access."""
    dept = db.get(Department, department_id)
    if not dept:
        raise ValueError("Department not found")
    if manager_id and manager_id == user.id:
        raise ValueError("A user cannot be their own manager.")
    prev = {"department": user.department.code if user.department else None, "manager_id": user.manager_id,
            "designation": user.designation}
    user.department_id = dept.id
    user.manager_id = manager_id
    if designation:
        user.designation = designation
    db.flush()
    db.refresh(user)
    grants = db.execute(select(AccessGrant).where(AccessGrant.user_id == user.id, AccessGrant.status == "ACTIVE")).scalars().all()
    from datetime import timedelta

    camp = AccessReviewCampaign(name=f"Mover review: {user.full_name}", due_at=utcnow() + timedelta(days=3),
                                created_by_id=actor.user.id)
    db.add(camp)
    db.flush()
    reviewer = manager_id or actor.user.id
    for g in grants:
        db.add(AccessReview(campaign_id=camp.id, reviewer_id=g.resource.owner_id if reviewer == user.id else reviewer,
                            grant_id=g.id, user_id=user.id, resource_id=g.resource_id, due_at=camp.due_at))
    audit.record(db, actor, "USER_TRANSFERRED", target_type="USER", target_id=user.id, previous_state=prev,
                 new_state={"department": dept.code, "manager_id": manager_id, "reviews_created": len(grants)})
    if grants:
        notify(db, reviewer, "RECERTIFICATION", f"Mover review: {user.full_name}",
               f"{user.full_name} moved to {dept.name}. Review {len(grants)} carried-over grant(s) within 3 days.",
               "/approvals?tab=reviews", "WARNING")
    db.commit()
    from app.services import drift

    drift.scan(db, None, [user.id])
    return {"reviews_created": len(grants)}
