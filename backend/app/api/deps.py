from __future__ import annotations

import hmac
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.db import get_db
from app.core.rbac import permissions_for
from app.models import User, UserSession, utcnow
from app.security import jwt_tokens

ACCESS_COOKIE = "astitva_at"
REFRESH_COOKIE = "astitva_rt"
CSRF_COOKIE = "astitva_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str:
    # Behind the Next.js proxy / a load balancer the first X-Forwarded-For hop is the client.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


@dataclass
class CurrentUser:
    user: User
    session: UserSession
    roles: list[str]
    permissions: set[str]
    actor: Actor

    @property
    def id(self) -> str:
        return self.user.id

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def _unauth(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = None
    via_cookie = False
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif request.cookies.get(ACCESS_COOKIE):
        token = request.cookies[ACCESS_COOKIE]
        via_cookie = True
    if not token:
        raise _unauth()
    try:
        claims = jwt_tokens.decode(token, "access")
    except jwt.PyJWTError:
        raise _unauth("Session expired or invalid")

    # CSRF: double-submit cookie check for state-changing cookie-authenticated requests.
    if via_cookie and request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not hmac.compare_digest(header, cookie):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

    sess = db.get(UserSession, claims.get("sid"))
    now = utcnow()
    if not sess or sess.revoked_at is not None or sess.expires_at < now or sess.user_id != claims["sub"]:
        raise _unauth("Session revoked")
    user = db.get(User, claims["sub"])
    if not user or user.status != "ACTIVE":
        raise _unauth("Account inactive")
    roles = user.role_names
    actor = Actor(user=user, ip=client_ip(request), user_agent=request.headers.get("user-agent"), roles=roles)
    if (now - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = now
        db.commit()
    return CurrentUser(user=user, session=sess, roles=roles, permissions=permissions_for(roles), actor=actor)


def require(*perms: str):
    """Dependency factory: caller must hold ALL listed permissions."""

    def dep(cu: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in perms if p not in cu.permissions]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {missing[0]}")
        return cu

    return dep


def require_any(*perms: str):
    def dep(cu: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(p in cu.permissions for p in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return cu

    return dep
