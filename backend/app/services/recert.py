"""Periodic access recertification campaigns."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import SYSTEM, Actor
from app.core.rbac import SECURITY_ADMIN
from app.models import AccessGrant, AccessReview, AccessReviewCampaign, ResourceAccessEvent, utcnow
from app.services import audit
from app.services.grants import restrict_grant, revoke_grant
from app.services.notify import notify, notify_role, raise_alert


class ReviewError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def start_campaign(db: Session, actor: Actor, name: str | None = None, reviewer_scope: str | None = None) -> AccessReviewCampaign:
    s = get_settings()
    now = utcnow()
    camp = AccessReviewCampaign(name=name or f"Access recertification {now:%B %Y}", due_at=now + timedelta(days=s.recertification_due_days),
                                created_by_id=actor.user.id if actor.user else None)
    db.add(camp)
    db.flush()
    grants = db.execute(select(AccessGrant).where(AccessGrant.status == "ACTIVE", AccessGrant.is_emergency.is_(False))).scalars().all()
    already = set(db.execute(select(AccessReview.grant_id).where(AccessReview.status == "PENDING")).scalars())
    reviewers: dict[str, int] = {}
    for g in grants:
        if g.id in already:
            continue
        reviewer = g.user.manager_id or g.resource.owner_id
        if reviewer == g.user_id:
            reviewer = g.resource.owner_id
        if not reviewer or reviewer == g.user_id:
            continue  # nobody independent to review (never self-review)
        if reviewer_scope and reviewer != reviewer_scope:
            continue
        used = db.scalar(select(ResourceAccessEvent.id).where(
            ResourceAccessEvent.grant_id == g.id, ResourceAccessEvent.outcome == "ALLOWED",
            ResourceAccessEvent.occurred_at >= now - timedelta(days=30)).limit(1))
        db.add(AccessReview(campaign_id=camp.id, reviewer_id=reviewer, grant_id=g.id, user_id=g.user_id,
                            resource_id=g.resource_id, unused=used is None, due_at=camp.due_at))
        reviewers[reviewer] = reviewers.get(reviewer, 0) + 1
    for rid, n in reviewers.items():
        notify(db, rid, "RECERTIFICATION", "Access review assigned",
               f"{n} access grant(s) need your review by {camp.due_at:%d %b %Y}.", "/approvals?tab=reviews", "INFO")
    audit.record(db, actor, "RECERT_CAMPAIGN_STARTED", target_type="CAMPAIGN", target_id=camp.id,
                 new_state={"items": sum(reviewers.values()), "reviewers": len(reviewers), "due_at": camp.due_at})
    db.commit()
    return camp


def decide(db: Session, actor: Actor, review_id: str, decision: str, comment: str | None,
           permissions: list[str] | None) -> AccessReview:
    rv = db.get(AccessReview, review_id)
    if not rv:
        raise ReviewError("Review not found", 404)
    if rv.reviewer_id != actor.user.id:
        raise ReviewError("This review is assigned to another reviewer.", 403)
    if rv.user_id == actor.user.id:
        raise ReviewError("You cannot recertify your own access.", 403)
    if rv.status != "PENDING":
        raise ReviewError("Review already decided.", 409)
    g = db.get(AccessGrant, rv.grant_id)
    if decision == "RETAIN":
        rv.status = "RETAINED"
    elif decision == "REVOKE":
        if g and g.status == "ACTIVE":
            revoke_grant(db, actor, g, f"Revoked in access review: {comment or 'no longer required'}")
        rv.status = "REVOKED"
    elif decision == "RESTRICT":
        try:
            restrict_grant(db, actor, g, permissions or [], f"Restricted in access review. {comment or ''}".strip())
        except ValueError as e:
            raise ReviewError(str(e), 422)
        rv.status = "RESTRICTED"
    else:
        raise ReviewError("Decision must be RETAIN, RESTRICT or REVOKE.", 422)
    rv.decided_at = utcnow()
    rv.comment = comment
    audit.record(db, actor, f"RECERT_{rv.status}", resource_id=rv.resource_id, target_type="ACCESS_REVIEW",
                 target_id=rv.id, new_state={"decision": decision, "grant": rv.grant_id, "permissions": permissions},
                 reason=comment)
    db.commit()
    return rv


def process_overdue(db: Session) -> int:
    now = utcnow()
    rows = db.execute(select(AccessReview).where(AccessReview.status == "PENDING", AccessReview.due_at < now,
                                                 AccessReview.overdue_alerted.is_(False))).scalars().all()
    by_reviewer: dict[str, list[AccessReview]] = {}
    for r in rows:
        r.overdue_alerted = True
        by_reviewer.setdefault(r.reviewer_id, []).append(r)
    for reviewer, items in by_reviewer.items():
        from app.models import User

        u = db.get(User, reviewer)
        notify(db, reviewer, "RECERTIFICATION_OVERDUE", "Access reviews overdue",
               f"{len(items)} access review(s) are past due. Unreviewed access remains a risk.", "/approvals?tab=reviews",
               "CRITICAL")
        raise_alert(db, "MEDIUM", "RECERT_OVERDUE", f"Overdue access reviews: {u.full_name if u else reviewer}",
                    f"{len(items)} recertification item(s) overdue.", user_id=reviewer, notify_admins=False)
        audit.record(db, SYSTEM, "RECERT_OVERDUE", target_type="USER", target_id=reviewer,
                     new_state={"items": [i.id for i in items]})
    if by_reviewer:
        notify_role(db, SECURITY_ADMIN, "RECERTIFICATION_OVERDUE", "Recertification overdue",
                    f"{len(rows)} review item(s) across {len(by_reviewer)} reviewer(s) are overdue.", "/audit?tab=alerts",
                    "WARNING")
    db.commit()
    return len(rows)


def maybe_auto_campaign(db: Session) -> AccessReviewCampaign | None:
    s = get_settings()
    last = db.execute(select(AccessReviewCampaign).order_by(AccessReviewCampaign.started_at.desc())).scalars().first()
    if last and last.started_at > utcnow() - timedelta(days=s.recertification_interval_days):
        return None
    return start_campaign(db, SYSTEM)
