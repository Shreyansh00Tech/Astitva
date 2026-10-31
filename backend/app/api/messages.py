"""Internal messaging API: private 1:1 chats between employees and managers (no Security Manager)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, CurrentUser, require
from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.models import User, UserSession, utcnow
from app.services import messaging as svc

router = APIRouter(prefix="/api", tags=["messages"])
member = require("messages:use")


def _err(e: svc.MessagingError):
    raise HTTPException(e.status, e.message)


@router.get("/messages/contacts")
def contacts(q: str | None = Query(None, max_length=80), cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    convs = {c["contact"]["id"]: c for c in svc.my_conversations(db, cu.user)}
    out = []
    for u in svc.contacts(db, cu.user, q):
        c = convs.get(u.id)
        out.append({**svc.contact_out(cu.user, u), "conversation_id": c["id"] if c else None,
                    "unread": c["unread"] if c else 0, "last_message": c["last_message"] if c else None})
    return out


@router.get("/messages/conversations")
def conversations(cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    return svc.my_conversations(db, cu.user)


@router.get("/messages/unread")
def unread(cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    return {"unread": svc.total_unread(db, cu.user)}


class OpenIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)


@router.post("/messages/conversations")
def open_conversation(body: OpenIn, cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    try:
        conv = svc.open_direct(db, cu.user, body.user_id)
    except svc.MessagingError as e:
        _err(e)
    db.commit()
    other = svc.other_member(db, conv.id, cu.id)
    return {"id": conv.id, "contact": svc.contact_out(cu.user, other)}


@router.get("/messages/conversations/{cid}")
def conversation(cid: str, before: datetime | None = None, limit: int = Query(50, ge=1, le=200),
                 cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    try:
        part = svc.require_member(db, cid, cu.id)
    except svc.MessagingError as e:
        _err(e)
    other = svc.other_member(db, cid, cu.id)
    rows = svc.history(db, cid, before, limit)
    other_part = svc._participant(db, cid, other.id) if other else None
    return {"id": cid, "contact": svc.contact_out(cu.user, other) if other else None,
            "can_send": svc.eligible(other), "messages": [svc.message_out(m) for m in rows],
            "has_more": len(rows) == limit, "my_last_read_at": part.last_read_at,
            "their_last_read_at": other_part.last_read_at if other_part else None}


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=svc.MAX_BODY)


@router.post("/messages/conversations/{cid}/messages")
def send(cid: str, body: SendIn, cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    try:
        m = svc.send(db, cu.user, cid, body.body)
    except svc.MessagingError as e:
        _err(e)
    db.commit()
    return svc.message_out(m)


@router.post("/messages/conversations/{cid}/read")
def read(cid: str, cu: CurrentUser = Depends(member), db: Session = Depends(get_db)):
    try:
        svc.mark_read(db, cu.user, cid)
    except svc.MessagingError as e:
        _err(e)
    db.commit()
    return {"ok": True, "read_at": utcnow()}


@router.websocket("/ws/messages")
async def ws_messages(ws: WebSocket):
    """Live chat push. Same cookie auth as /ws/notifications; only events naming this user are relayed."""
    from app.security import jwt_tokens

    try:
        claims = jwt_tokens.decode(ws.cookies.get(ACCESS_COOKIE) or "", "access")
    except Exception:
        await ws.close(code=4401)
        return
    with SessionLocal() as db:
        sess = db.get(UserSession, claims.get("sid"))
        user = db.get(User, claims.get("sub"))
        if not sess or sess.revoked_at or sess.expires_at < utcnow() or not svc.eligible(user):
            await ws.close(code=4403)
            return
    user_id = claims["sub"]
    await ws.accept()
    import redis.asyncio as aioredis

    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(svc.CHANNEL)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=20)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                if user_id in data.get("recipients", []):
                    if "message" in data:
                        await ws.send_json({"type": "chat", "message": data["message"], "sender_name": data.get("sender_name")})
                    elif "read" in data:
                        await ws.send_json({"type": "read", "conversation_id": data["read"]})
            else:
                await ws.send_json({"type": "ping"})
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await pubsub.unsubscribe(svc.CHANNEL)
        await r.aclose()
