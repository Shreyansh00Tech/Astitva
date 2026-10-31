"""Internal messaging between employees and managers.

Only users for whom ``rbac.can_message`` is true take part: the Security Manager / security review
roles are deliberately left out. Every read and write checks that the caller is a participant of the
conversation, so a user can never see a chat they do not belong to.
Live delivery reuses the Redis pub/sub pattern from notifications, published only after commit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from app.core.rbac import can_message
from app.models import ChatMessage, Conversation, ConversationParticipant, User, utcnow

log = logging.getLogger("astitva.messaging")
CHANNEL = "astitva:messages"
MAX_BODY = 2000
_PENDING = "astitva_pending_chat"


class MessagingError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def eligible(u: User | None) -> bool:
    return bool(u and u.status == "ACTIVE" and not u.is_service_account and can_message(u.role_names))


def pair_key(a: str, b: str) -> str:
    return ":".join(sorted((a, b)))


def relation(me: User, other: User) -> str:
    if me.manager_id == other.id:
        return "Your manager"
    if other.manager_id == me.id:
        return "Your team"
    if me.manager_id and me.manager_id == other.manager_id:
        return "Teammate"
    return "Colleague"


def contact_out(me: User, u: User) -> dict:
    return {"id": u.id, "name": u.full_name, "email": u.email, "designation": u.designation,
            "department": u.department.name if u.department else None, "employee_id": u.employee_id,
            "is_manager": "MANAGER" in u.role_names, "relation": relation(me, u)}


def message_out(m: ChatMessage) -> dict:
    return {"id": m.id, "conversation_id": m.conversation_id, "sender_id": m.sender_id, "body": m.body,
            "created_at": m.created_at}


def _participant(db: Session, conversation_id: str, user_id: str) -> ConversationParticipant | None:
    return db.get(ConversationParticipant, (conversation_id, user_id))


def require_member(db: Session, conversation_id: str, user_id: str) -> ConversationParticipant:
    """404 (not 403) for non-members, so conversation ids cannot be probed."""
    p = _participant(db, conversation_id, user_id)
    if not p:
        raise MessagingError(404, "Conversation not found")
    return p


def other_member(db: Session, conversation_id: str, user_id: str) -> User | None:
    uid = db.scalar(select(ConversationParticipant.user_id).where(
        ConversationParticipant.conversation_id == conversation_id, ConversationParticipant.user_id != user_id))
    return db.get(User, uid) if uid else None


def contacts(db: Session, me: User, q: str | None = None) -> list[User]:
    stmt = select(User).where(User.id != me.id, User.status == "ACTIVE", User.is_service_account.is_(False))
    if q:
        like = f"%{q.strip()[:80]}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.designation.ilike(like),
                              User.employee_id.ilike(like)))
    return [u for u in db.execute(stmt.order_by(User.full_name)).scalars().unique() if eligible(u)]


def unread_count(db: Session, conversation_id: str, user_id: str, last_read_at: datetime | None) -> int:
    stmt = select(func.count()).select_from(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id, ChatMessage.sender_id != user_id)
    if last_read_at:
        stmt = stmt.where(ChatMessage.created_at > last_read_at)
    return db.scalar(stmt) or 0


def last_message(db: Session, conversation_id: str) -> ChatMessage | None:
    return db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(ChatMessage.created_at.desc()).limit(1)).scalar_one_or_none()


def my_conversations(db: Session, me: User) -> list[dict]:
    rows = db.execute(select(Conversation, ConversationParticipant)
                      .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
                      .where(ConversationParticipant.user_id == me.id)).all()
    out = []
    for conv, part in rows:
        other = other_member(db, conv.id, me.id)
        if not eligible(other):
            continue  # the other person left the messaging group (deactivated or moved to security)
        last = last_message(db, conv.id)
        out.append({"id": conv.id, "contact": contact_out(me, other), "last_message": message_out(last) if last else None,
                    "last_message_at": conv.last_message_at,
                    "unread": unread_count(db, conv.id, me.id, part.last_read_at)})
    out.sort(key=lambda c: c["last_message_at"] or datetime.min.replace(tzinfo=utcnow().tzinfo), reverse=True)
    return out


def total_unread(db: Session, me: User) -> int:
    return sum(c["unread"] for c in my_conversations(db, me))


def open_direct(db: Session, me: User, other_id: str) -> Conversation:
    if other_id == me.id:
        raise MessagingError(400, "You cannot start a conversation with yourself")
    other = db.get(User, other_id)
    if not eligible(other):
        # Same answer for unknown users and the Security Manager: neither is a messaging contact.
        raise MessagingError(404, "Contact not found")
    key = pair_key(me.id, other.id)
    conv = db.execute(select(Conversation).where(Conversation.pair_key == key)).scalar_one_or_none()
    if conv:
        return conv
    conv = Conversation(pair_key=key)
    db.add(conv)
    db.flush()
    db.add_all([ConversationParticipant(conversation_id=conv.id, user_id=me.id),
                ConversationParticipant(conversation_id=conv.id, user_id=other.id)])
    db.flush()
    return conv


def history(db: Session, conversation_id: str, before: datetime | None = None, limit: int = 50) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before:
        stmt = stmt.where(ChatMessage.created_at < before)
    rows = db.execute(stmt.order_by(ChatMessage.created_at.desc()).limit(limit)).scalars().all()
    return list(reversed(rows))


def send(db: Session, me: User, conversation_id: str, body: str) -> ChatMessage:
    me_part = require_member(db, conversation_id, me.id)
    text = (body or "").strip()
    if not text:
        raise MessagingError(422, "Message cannot be empty")
    if len(text) > MAX_BODY:
        raise MessagingError(422, f"Message is longer than {MAX_BODY} characters")
    other = other_member(db, conversation_id, me.id)
    if not eligible(other):
        raise MessagingError(403, "This person can no longer receive messages")
    now = utcnow()
    m = ChatMessage(conversation_id=conversation_id, sender_id=me.id, body=text, created_at=now)
    db.add(m)
    conv = db.get(Conversation, conversation_id)
    conv.last_message_at = now
    me_part.last_read_at = now  # your own message is read by you
    db.flush()
    db.info.setdefault(_PENDING, []).append({"recipients": [me.id, other.id], "message": json.loads(json.dumps(
        message_out(m), default=str)), "sender_name": me.full_name})
    return m


def mark_read(db: Session, me: User, conversation_id: str) -> None:
    p = require_member(db, conversation_id, me.id)
    p.last_read_at = utcnow()
    db.info.setdefault(_PENDING, []).append({"recipients": [me.id], "read": conversation_id})


@event.listens_for(Session, "after_commit")
def _publish(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    try:
        from app.security.ratelimit import get_redis

        r = get_redis()
        for p in pending:
            r.publish(CHANNEL, json.dumps(p))
    except Exception as exc:  # live push is best-effort; the message is already stored
        log.debug("chat publish failed: %s", exc)


@event.listens_for(Session, "after_rollback")
def _drop(session: Session) -> None:
    session.info.pop(_PENDING, None)
