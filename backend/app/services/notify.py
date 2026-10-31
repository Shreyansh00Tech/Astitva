"""In-app notifications and security alerts. Live delivery via Redis pub/sub after commit."""
from __future__ import annotations

import json
import logging

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.rbac import SECURITY_ADMIN
from app.models import Notification, Role, SecurityAlert, User, UserRole

log = logging.getLogger("astitva.notify")
CHANNEL = "astitva:notifications"


def notify(db: Session, user_id: str, kind: str, title: str, body: str, link: str | None = None,
           severity: str = "INFO") -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title, body=body, link=link, severity=severity)
    db.add(n)
    db.flush()
    db.info.setdefault("astitva_pending_pub", []).append({"user_id": user_id, "id": n.id, "kind": kind,
                                                          "title": title, "severity": severity})
    return n


def users_with_role(db: Session, role: str) -> list[User]:
    return list(db.execute(
        select(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
        .where(Role.name == role, User.status == "ACTIVE")
    ).scalars().unique())


def notify_role(db: Session, role: str, kind: str, title: str, body: str, link: str | None = None,
                severity: str = "INFO", exclude: set[str] | None = None) -> None:
    for u in users_with_role(db, role):
        if exclude and u.id in exclude:
            continue
        notify(db, u.id, kind, title, body, link, severity)


def raise_alert(db: Session, severity: str, category: str, title: str, description: str, *,
                user_id: str | None = None, agent_id: str | None = None, resource_id: str | None = None,
                details: dict | None = None, notify_admins: bool = True) -> SecurityAlert:
    a = SecurityAlert(severity=severity, category=category, title=title, description=description,
                      user_id=user_id, agent_id=agent_id, resource_id=resource_id, details=details)
    db.add(a)
    db.flush()
    if notify_admins:
        notify_role(db, SECURITY_ADMIN, "SECURITY_ALERT", title, description, "/audit?tab=alerts",
                    severity if severity in ("HIGH", "CRITICAL") else "WARNING")
    return a


@event.listens_for(Session, "after_commit")
def _publish(session: Session) -> None:
    pending = session.info.pop("astitva_pending_pub", None)
    if not pending:
        return
    try:
        from app.security.ratelimit import get_redis

        r = get_redis()
        for p in pending:
            r.publish(CHANNEL, json.dumps(p))
    except Exception as exc:  # live push is best-effort; data is already persisted
        log.debug("notification publish failed: %s", exc)


@event.listens_for(Session, "after_rollback")
def _drop(session: Session) -> None:
    session.info.pop("astitva_pending_pub", None)
