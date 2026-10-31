"""Access grants and purpose-bound simulated tokens."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import SYSTEM, Actor
from app.models import AccessGrant, AccessToken, EmergencySession, utcnow
from app.security import crypto
from app.services import audit
from app.services.notify import notify

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def issue_token(db: Session, grant: AccessGrant, approval_ref: str | None) -> tuple[AccessToken, str]:
    """Token format: SIM-ACCESS-<7 char id>.<secret>. The public id is shown in UIs; the full value is the bearer secret."""
    public = "".join(secrets.choice(_ALPHABET) for _ in range(7))
    token = f"SIM-ACCESS-{public}.{secrets.token_urlsafe(24)}"
    t = AccessToken(token_hash=crypto.token_digest(token), token_hint=f"SIM-ACCESS-{public}",
                    token_encrypted=crypto.encrypt(token), grant_id=grant.id, user_id=grant.user_id,
                    resource_id=grant.resource_id, request_id=grant.request_id, approval_ref=approval_ref,
                    purpose=grant.purpose, permissions=list(grant.permissions), expires_at=grant.expires_at)
    db.add(t)
    db.flush()
    return t, token


def create_grant(db: Session, actor: Actor, *, user_id: str, resource_id: str, permissions: list[str], purpose: str,
                 hours: float | None, request_id: str | None = None, source: str = "REQUEST",
                 is_emergency: bool = False, approval_ref: str | None = None) -> tuple[AccessGrant, AccessToken]:
    now = utcnow()
    g = AccessGrant(user_id=user_id, resource_id=resource_id, request_id=request_id, permissions=list(permissions),
                    purpose=purpose, source=source, is_emergency=is_emergency, granted_at=now,
                    expires_at=(now + timedelta(hours=hours)) if hours else None)
    db.add(g)
    db.flush()
    tok, _ = issue_token(db, g, approval_ref) if g.expires_at else (None, None)
    audit.record(db, actor, "GRANT_ACTIVATED", resource_id=resource_id, target_type="GRANT", target_id=g.id,
                 request_id=request_id, new_state={"user_id": user_id, "permissions": permissions, "purpose": purpose,
                                                   "expires_at": g.expires_at, "emergency": is_emergency,
                                                   "token": tok.token_hint if tok else None})
    return g, tok


def revoke_grant(db: Session, actor: Actor, grant: AccessGrant, reason: str, status: str = "REVOKED") -> bool:
    if grant.status != "ACTIVE":
        return False
    prev = {"status": grant.status, "permissions": grant.permissions}
    grant.status = status
    grant.revoked_at = utcnow()
    grant.revoked_by_id = actor.user.id if actor.user else None
    grant.revoked_by = actor.user if actor.user else None
    grant.revoke_reason = reason
    for t in db.execute(select(AccessToken).where(AccessToken.grant_id == grant.id, AccessToken.revoked_at.is_(None))).scalars():
        t.revoked_at = utcnow()
    audit.record(db, actor, "GRANT_EXPIRED" if status == "EXPIRED" else "GRANT_REVOKED", resource_id=grant.resource_id,
                 target_type="GRANT", target_id=grant.id, request_id=grant.request_id, previous_state=prev,
                 new_state={"status": status}, reason=reason)
    if status == "EXPIRED":
        notify(db, grant.user_id, "ACCESS_EXPIRED", f"Access expired: {grant.resource.name}",
               f"Your {', '.join(grant.permissions)} access for {grant.purpose.replace('_', ' ').title()} has expired.",
               "/active-access", "INFO")
    else:
        notify(db, grant.user_id, "ACCESS_REVOKED", f"Access revoked: {grant.resource.name}", reason, "/active-access",
               "WARNING")
    return True


def restrict_grant(db: Session, actor: Actor, grant: AccessGrant, permissions: list[str], reason: str) -> None:
    """Reduce a grant to a strict subset of its permissions and reissue a narrowed token."""
    keep = [p for p in grant.permissions if p in permissions]
    if not keep or set(keep) == set(grant.permissions):
        raise ValueError("Restriction must be a non-empty strict subset of current permissions.")
    prev = list(grant.permissions)
    grant.permissions = keep
    for t in db.execute(select(AccessToken).where(AccessToken.grant_id == grant.id, AccessToken.revoked_at.is_(None))).scalars():
        t.revoked_at = utcnow()
    if grant.expires_at:
        issue_token(db, grant, f"RESTRICT-{grant.id[:8]}")
    audit.record(db, actor, "GRANT_RESTRICTED", resource_id=grant.resource_id, target_type="GRANT", target_id=grant.id,
                 request_id=grant.request_id,
                 previous_state={"permissions": prev}, new_state={"permissions": keep}, reason=reason)
    notify(db, grant.user_id, "PERMISSION_NARROWED", f"Access restricted: {grant.resource.name}",
           f"Permissions reduced from {', '.join(prev)} to {', '.join(keep)}. {reason}", "/active-access", "WARNING")


def expire_due(db: Session, now: datetime | None = None) -> int:
    """Expire grants/tokens/emergency sessions past their expiry. Enforcement also checks expiry in real time."""
    now = now or utcnow()
    n = 0
    for g in db.execute(select(AccessGrant).where(AccessGrant.status == "ACTIVE", AccessGrant.expires_at.is_not(None),
                                                  AccessGrant.expires_at <= now)).scalars().all():
        revoke_grant(db, SYSTEM, g, "Grant reached its expiry time", status="EXPIRED")
        n += 1
    for es in db.execute(select(EmergencySession).where(EmergencySession.status == "ACTIVE",
                                                        EmergencySession.expires_at <= now)).scalars().all():
        es.status = "EXPIRED"
        es.ended_at = now
        audit.record(db, SYSTEM, "BREAKGLASS_EXPIRED", resource_id=es.resource_id, target_type="EMERGENCY_SESSION",
                     target_id=es.id, new_state={"status": "EXPIRED", "review_status": es.review_status})
    return n
