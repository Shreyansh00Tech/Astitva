"""SHA-256 hash-chained audit trail.

Each event stores the hash of the previous event, and its own hash covers all of its
fields plus that previous hash. Any modification, deletion or reordering of a historical
record breaks the chain and is detected by `verify_chain`. This makes tampering
*detectable*; it does not make the underlying storage immutable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.models import AuditChainHead, AuditEvent, new_id, utcnow

GENESIS_HASH = "0" * 64
HASHED_FIELDS = (
    "seq", "event_id", "occurred_at", "actor_type", "actor_id", "actor_name", "actor_role", "action",
    "resource_id", "target_type", "target_id", "request_id", "previous_state", "new_state", "reason",
    "ip", "user_agent", "prev_hash",
)


def _norm(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return value


def compute_hash(event: AuditEvent) -> str:
    payload = {f: _norm(getattr(event, f)) for f in HASHED_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _lock_head(db: Session) -> AuditChainHead:
    head = db.execute(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()).scalar_one_or_none()
    if head is None:
        head = AuditChainHead(id=1, last_seq=0, last_hash=GENESIS_HASH)
        db.add(head)
        db.flush()
        head = db.execute(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()).scalar_one()
    return head


def record(
    db: Session,
    actor: Actor,
    action: str,
    *,
    resource_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Append an audit event within the caller's transaction (atomic with the business change)."""
    head = _lock_head(db)
    ts = occurred_at or utcnow()
    ev = AuditEvent(
        seq=head.last_seq + 1,
        event_id=new_id(),
        occurred_at=ts.replace(microsecond=ts.microsecond),
        actor_type=actor.actor_type,
        actor_id=actor.id,
        actor_name=actor.display_name,
        actor_role=actor.role_label,
        action=action,
        resource_id=resource_id,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        previous_state=_jsonable(previous_state),
        new_state=_jsonable(new_state),
        reason=reason,
        ip=actor.ip,
        user_agent=(actor.user_agent or None) and actor.user_agent[:255],
        prev_hash=head.last_hash,
    )
    ev.hash = compute_hash(ev)
    db.add(ev)
    head.last_seq = ev.seq
    head.last_hash = ev.hash
    db.flush()
    return ev


def _jsonable(d):
    if d is None:
        return None
    return json.loads(json.dumps(d, default=lambda v: _norm(v) if isinstance(v, datetime) else str(v)))


def verify_chain(db: Session, batch: int = 2000) -> dict:
    """Recalculate every hash and check linkage. Reports the first invalid event."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    last_seq = 0
    while True:
        rows = db.execute(
            select(AuditEvent).where(AuditEvent.seq > last_seq).order_by(AuditEvent.seq).limit(batch)
        ).scalars().all()
        if not rows:
            break
        for ev in rows:
            problem = None
            if ev.seq != expected_seq:
                problem = f"Sequence gap: expected #{expected_seq}, found #{ev.seq} (record deleted?)"
            elif ev.prev_hash != expected_prev:
                problem = "Previous-hash link broken (record reordered, deleted or chain rewritten)"
            elif compute_hash(ev) != ev.hash:
                problem = "Content hash mismatch (record contents were modified)"
            if problem:
                return {
                    "valid": False, "checked": checked, "first_invalid_seq": ev.seq,
                    "first_invalid_event_id": ev.event_id, "problem": problem,
                    "action": ev.action, "occurred_at": ev.occurred_at,
                }
            expected_prev = ev.hash
            expected_seq += 1
            checked += 1
            last_seq = ev.seq
    head = db.get(AuditChainHead, 1)
    if head and checked and head.last_hash != expected_prev:
        return {"valid": False, "checked": checked, "first_invalid_seq": head.last_seq,
                "first_invalid_event_id": None, "problem": "Chain head does not match last event (tail truncated?)"}
    return {"valid": True, "checked": checked, "first_invalid_seq": None, "problem": None,
            "head_hash": expected_prev}
