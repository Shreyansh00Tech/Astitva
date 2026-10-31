"""Periodic jobs. Run by Celery beat in Docker; an in-process loop is available for local dev."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AccessGrant, EmergencySession, utcnow
from app.services import drift, recert
from app.services.grants import expire_due
from app.services.notify import notify, raise_alert

log = logging.getLogger("astitva.maintenance")


def expire_and_warn() -> dict:
    s = get_settings()
    with SessionLocal() as db:
        expired = expire_due(db)
        soon = utcnow() + timedelta(hours=s.expiring_soon_hours)
        warned = 0
        for g in db.execute(select(AccessGrant).where(AccessGrant.status == "ACTIVE", AccessGrant.expires_at.is_not(None),
                                                      AccessGrant.expires_at <= soon,
                                                      AccessGrant.expiry_notified.is_(False),
                                                      AccessGrant.is_emergency.is_(False))).scalars():
            g.expiry_notified = True
            hours = max(1, int((g.expires_at - utcnow()).total_seconds() // 3600))
            notify(db, g.user_id, "ACCESS_EXPIRING", f"Access expiring soon: {g.resource.name}",
                   f"Your {', '.join(g.permissions)} access expires in about {hours}h.", "/active-access", "WARNING")
            warned += 1
        # Post-incident reviews outstanding for more than 24h after the session ended
        for es in db.execute(select(EmergencySession).where(EmergencySession.status != "ACTIVE",
                                                            EmergencySession.review_status == "PENDING",
                                                            EmergencySession.ended_at < utcnow() - timedelta(hours=24))).scalars():
            if not (es.review_notes or "").startswith("[reminded]"):
                es.review_notes = "[reminded]"
                raise_alert(db, "MEDIUM", "BREAKGLASS_REVIEW_OVERDUE", f"Post-incident review overdue: {es.ref}",
                            f"Break-glass session by {es.user.full_name} ended over 24h ago without review.",
                            user_id=es.user_id, resource_id=es.resource_id)
        db.commit()
        return {"expired": expired, "warned": warned}


def recertification() -> dict:
    with SessionLocal() as db:
        camp = recert.maybe_auto_campaign(db)
        overdue = recert.process_overdue(db)
        return {"campaign": camp.id if camp else None, "overdue": overdue}


def drift_scan() -> dict:
    with SessionLocal() as db:
        return drift.scan(db)


def run_all() -> dict:
    out = {}
    for name, fn in (("expiry", expire_and_warn), ("recert", recertification), ("drift", drift_scan)):
        try:
            out[name] = fn()
        except Exception as exc:
            log.exception("maintenance job %s failed: %s", name, exc)
    return out
