"""Emergency break-glass access with mandatory justification, monitoring, auto-expiry and post-incident review."""
from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.catalog import sort_perms
from app.core.config import get_settings
from app.core.context import Actor
from app.core.rbac import RISK_REVIEWER, SECURITY_ADMIN
from app.models import EmergencySession, Resource, utcnow
from app.services import audit
from app.services.grants import create_grant, revoke_grant
from app.services.notify import notify, notify_role, raise_alert

ELIGIBLE_DEPARTMENTS = {"ENG", "SEC"}


class BreakGlassError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def activate(db: Session, actor: Actor, *, resource_id: str, permissions: list[str], justification: str,
             incident_ref: str, duration_minutes: int | None) -> tuple[EmergencySession, str]:
    s = get_settings()
    user = actor.user
    res = db.get(Resource, resource_id)
    if not res:
        raise BreakGlassError("Resource not found", 404)
    if not res.breakglass_allowed:
        raise BreakGlassError(f"Break-glass access is not enabled for {res.name}.", 403)
    dept = user.department.code if user.department else None
    if dept not in ELIGIBLE_DEPARTMENTS:
        raise BreakGlassError("Only on-call Engineering or Security staff are eligible for break-glass access.", 403)
    if len(justification.strip()) < 30:
        raise BreakGlassError("Justification must be at least 30 characters.", 422)
    if not re.fullmatch(r"INC-\d{3,8}", incident_ref.strip().upper()):
        raise BreakGlassError("Incident reference must look like INC-12345.", 422)
    perms = sort_perms(permissions)
    if not perms or any(p not in res.available_permissions for p in perms) or "ADMIN" in perms:
        raise BreakGlassError("Choose valid permissions (ADMIN is never available via break-glass).", 422)
    minutes = duration_minutes or s.breakglass_default_minutes
    if not 5 <= minutes <= s.breakglass_max_minutes:
        raise BreakGlassError(f"Duration must be between 5 and {s.breakglass_max_minutes} minutes.", 422)
    active = db.scalar(select(func.count()).select_from(EmergencySession).where(
        EmergencySession.user_id == user.id, EmergencySession.status == "ACTIVE")) or 0
    if active >= 1:
        raise BreakGlassError("You already have an active break-glass session.", 409)

    grant, tok = create_grant(db, actor, user_id=user.id, resource_id=res.id, permissions=perms,
                              purpose="INCIDENT_RESPONSE", hours=minutes / 60, source="EMERGENCY", is_emergency=True,
                              approval_ref=f"BREAKGLASS-{incident_ref.upper()}")
    from app.security import crypto

    raw = crypto.decrypt(tok.token_encrypted)
    es = EmergencySession(ref=f"BG-{secrets.token_hex(3).upper()}", user_id=user.id, resource_id=res.id,
                          grant_id=grant.id, justification=justification.strip(), incident_ref=incident_ref.upper(),
                          permissions=perms, expires_at=grant.expires_at)
    db.add(es)
    db.flush()
    audit.record(db, actor, "BREAKGLASS_ACTIVATED", resource_id=res.id, target_type="EMERGENCY_SESSION", target_id=es.ref,
                 new_state={"permissions": perms, "minutes": minutes, "incident": es.incident_ref, "token": tok.token_hint},
                 reason=justification)
    raise_alert(db, "CRITICAL", "BREAKGLASS", f"BREAK-GLASS activated by {user.full_name}",
                f"{', '.join(perms)} on {res.name} for {minutes} min. Incident {es.incident_ref}: {justification[:160]}",
                user_id=user.id, resource_id=res.id, details={"session": es.ref})
    notify_role(db, RISK_REVIEWER, "EMERGENCY_ACCESS", f"Break-glass activated: {res.name}",
                f"{user.full_name} ({es.incident_ref}) - {minutes} min", "/emergency", "CRITICAL")
    for uid in {res.owner_id, user.manager_id} - {None, user.id}:
        notify(db, uid, "EMERGENCY_ACCESS", f"Break-glass activated: {res.name}",
               f"{user.full_name} activated emergency access for {es.incident_ref}.", "/emergency", "CRITICAL")
    db.commit()
    return es, raw


def revoke(db: Session, actor: Actor, session_id: str, reason: str) -> EmergencySession:
    es = db.get(EmergencySession, session_id)
    if not es:
        raise BreakGlassError("Session not found", 404)
    if es.status != "ACTIVE":
        raise BreakGlassError("Session is no longer active.", 409)
    roles = set(actor.user.role_names)
    if not (SECURITY_ADMIN in roles or RISK_REVIEWER in roles or actor.user.id in (es.resource.owner_id, es.user_id)):
        raise BreakGlassError("Not authorized to revoke this session.", 403)
    es.status = "REVOKED"
    es.ended_at = utcnow()
    es.revoked_by_id = actor.user.id
    from app.models import AccessGrant

    g = db.get(AccessGrant, es.grant_id)
    if g:
        revoke_grant(db, actor, g, f"Break-glass session revoked: {reason}")
    audit.record(db, actor, "BREAKGLASS_REVOKED", resource_id=es.resource_id, target_type="EMERGENCY_SESSION",
                 target_id=es.ref, previous_state={"status": "ACTIVE"}, new_state={"status": "REVOKED"}, reason=reason)
    notify_role(db, SECURITY_ADMIN, "EMERGENCY_ACCESS", f"Break-glass revoked: {es.ref}",
                f"{actor.display_name} revoked {es.user.full_name}'s session. {reason}", "/emergency", "WARNING")
    db.commit()
    return es


def review(db: Session, actor: Actor, session_id: str, outcome: str, notes: str) -> EmergencySession:
    es = db.get(EmergencySession, session_id)
    if not es:
        raise BreakGlassError("Session not found", 404)
    if es.status == "ACTIVE":
        raise BreakGlassError("Post-incident review happens after the session ends.", 409)
    if es.user_id == actor.user.id:
        raise BreakGlassError("You cannot review your own break-glass session.", 403)
    if outcome not in ("JUSTIFIED", "MISUSE", "INCONCLUSIVE") or len(notes.strip()) < 10:
        raise BreakGlassError("Provide an outcome and review notes.", 422)
    es.review_status = "COMPLETED"
    es.review_outcome = outcome
    es.review_notes = notes
    es.reviewed_by_id = actor.user.id
    es.reviewed_at = utcnow()
    audit.record(db, actor, "BREAKGLASS_REVIEWED", resource_id=es.resource_id, target_type="EMERGENCY_SESSION",
                 target_id=es.ref, new_state={"outcome": outcome}, reason=notes)
    if outcome == "MISUSE":
        raise_alert(db, "HIGH", "BREAKGLASS_MISUSE", f"Break-glass misuse confirmed: {es.ref}", notes, user_id=es.user_id,
                    resource_id=es.resource_id)
    db.commit()
    return es
