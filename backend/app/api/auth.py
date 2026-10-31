from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, CurrentUser, client_ip, get_current_user
from app.api.serializers import user_brief
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rbac import REQUESTER
from app.models import DevOutbox, MfaCredential, Role, User, UserSession, utcnow
from app.security import crypto
from app.security.password_policy import evaluate_password
from app.services import audit
from app.services import auth as svc

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _err(e: svc.AuthError) -> JSONResponse:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return JSONResponse({"detail": e.message, "code": e.code, "retry_after": e.retry_after}, e.status, headers=headers)


def _set_session_cookies(resp: Response, tokens: svc.SessionTokens) -> None:
    s = get_settings()
    common = dict(secure=s.cookie_secure, samesite=s.cookie_samesite, domain=s.cookie_domain)
    resp.set_cookie(ACCESS_COOKIE, tokens.access_token, max_age=s.access_token_ttl_seconds, httponly=True, path="/",
                    **common)
    resp.set_cookie(REFRESH_COOKIE, tokens.refresh_token, max_age=s.refresh_token_ttl_seconds, httponly=True,
                    path="/api/auth", **common)
    resp.set_cookie(CSRF_COOKIE, crypto.random_token(24), max_age=s.refresh_token_ttl_seconds, httponly=False,
                    path="/", **common)


def _clear_cookies(resp: Response) -> None:
    s = get_settings()
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        resp.delete_cookie(name, path=path, domain=s.cookie_domain)


def _me(cu_user: User, perms: set[str], session_id: str | None = None) -> dict:
    return {**user_brief(cu_user), "roles": cu_user.role_names, "permissions": sorted(perms),
            "mfa_enabled": cu_user.mfa_enabled, "email_verified": cu_user.email_verified, "session_id": session_id,
            "manager": user_brief(cu_user.manager) if cu_user.manager else None}


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    captcha_token: str | None = None


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    try:
        res = svc.start_login(db, body.email, body.password, client_ip(request), request.headers.get("user-agent"),
                              body.captcha_token)
    except svc.AuthError as e:
        return _err(e)
    return {"mfa_required": True, "mfa_token": res.mfa_token, "methods": res.methods, "destination": res.destination}


class MfaVerifyIn(BaseModel):
    mfa_token: str
    method: str = Field(pattern="^(TOTP|EMAIL|SMS|BACKUP_CODE)$")
    code: str = Field(min_length=4, max_length=16)
    return_tokens: bool = False  # API clients (CLI/tests) may request tokens in the body


@router.post("/mfa/verify")
def mfa_verify(body: MfaVerifyIn, request: Request, db: Session = Depends(get_db)):
    try:
        tokens = svc.complete_mfa(db, body.mfa_token, body.method, body.code, client_ip(request),
                                  request.headers.get("user-agent"))
    except svc.AuthError as e:
        return _err(e)
    from app.core.rbac import permissions_for

    payload = {"user": _me(tokens.user, permissions_for(tokens.user.role_names), tokens.session.id)}
    if body.return_tokens:
        payload |= {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token}
    resp = JSONResponse(payload)
    _set_session_cookies(resp, tokens)
    return resp


class ResendIn(BaseModel):
    mfa_token: str
    channel: str = Field(default="EMAIL", pattern="^(EMAIL|SMS)$")


@router.post("/mfa/resend")
def mfa_resend(body: ResendIn, request: Request, db: Session = Depends(get_db)):
    try:
        dest = svc.resend_login_otp(db, body.mfa_token, body.channel, client_ip(request))
    except svc.AuthError as e:
        return _err(e)
    return {"sent": True, "destination": dest}


class RefreshIn(BaseModel):
    refresh_token: str | None = None


@router.post("/refresh")
def refresh(request: Request, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        return _err(svc.AuthError("Session expired. Please sign in again.", 401, "REFRESH_MISSING"))
    try:
        tokens = svc.rotate_refresh(db, token, client_ip(request), request.headers.get("user-agent"))
    except svc.AuthError as e:
        resp = _err(e)
        _clear_cookies(resp)
        return resp
    payload = {"ok": True}
    if body and body.refresh_token:
        payload |= {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token}
    resp = JSONResponse(payload)
    _set_session_cookies(resp, tokens)
    return resp


@router.post("/logout")
def logout(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.revoke_session(db, cu.session, "LOGOUT")
    audit.record(db, cu.actor, "AUTH_LOGOUT", target_type="SESSION", target_id=cu.session.id)
    db.commit()
    resp = JSONResponse({"ok": True})
    _clear_cookies(resp)
    return resp


@router.get("/me")
def me(cu: CurrentUser = Depends(get_current_user)):
    return _me(cu.user, cu.permissions, cu.session.id)


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=1, max_length=256)


@router.post("/register", status_code=202)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    from app.security import ratelimit

    ip = client_ip(request)
    if not ratelimit.take(f"register:ip:{ip}", 5, 5 / 3600).allowed:
        raise HTTPException(429, "Too many registrations from this network. Try again later.")
    verdict = evaluate_password(body.password, body.email, body.full_name)
    if not verdict["ok"]:
        raise HTTPException(422, {"message": "Password does not meet the policy.", "problems": verdict["problems"]})
    email = body.email.strip().lower()
    generic = {"message": "If this address can be registered, a verification code has been sent."}
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        return generic  # do not reveal existing accounts
    count = db.query(User).count()
    user = User(email=email, full_name=body.full_name.strip(), password_hash=crypto.hash_password(body.password),
                employee_id=f"NX-{9000 + count:05d}", designation="New Joiner", password_changed_at=utcnow())
    user.roles = [db.execute(select(Role).where(Role.name == REQUESTER)).scalar_one()]
    db.add(user)
    db.flush()
    svc.send_email_verification(db, user)
    from app.core.context import Actor

    audit.record(db, Actor(user=user, ip=ip), "AUTH_REGISTERED", target_type="USER", target_id=user.id)
    db.commit()
    return generic


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


@router.post("/verify-email")
def verify_email(body: VerifyEmailIn, db: Session = Depends(get_db)):
    try:
        ok = svc.verify_email(db, body.email, body.code)
    except svc.AuthError as e:
        return _err(e)
    if not ok:
        raise HTTPException(400, "Invalid or expired code.")
    return {"verified": True}


class ResendVerifyIn(BaseModel):
    email: EmailStr


@router.post("/verify-email/resend", status_code=202)
def resend_verify(body: ResendVerifyIn, request: Request, db: Session = Depends(get_db)):
    from app.security import ratelimit

    if ratelimit.take(f"verify-resend:{body.email.lower()}", 3, 3 / 900).allowed:
        user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
        if user and not user.email_verified:
            svc.send_email_verification(db, user)
            db.commit()
    return {"message": "If the account exists and is unverified, a new code was sent."}


class ForgotIn(BaseModel):
    email: EmailStr


@router.post("/forgot-password", status_code=202)
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    svc.request_password_reset(db, body.email, client_ip(request))
    return {"message": "If an account exists for this email, a reset link has been sent."}


class ResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/reset-password")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    try:
        svc.reset_password(db, body.token, body.new_password, client_ip(request))
    except svc.AuthError as e:
        return _err(e)
    return {"ok": True}


class StrengthIn(BaseModel):
    password: str = Field(max_length=256)
    email: str | None = None
    name: str | None = None


@router.post("/password-strength")
def strength(body: StrengthIn):
    return evaluate_password(body.password, body.email, body.name)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/password/change")
def change_password(body: ChangePasswordIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if not crypto.verify_password(cu.user.password_hash, body.current_password):
        raise HTTPException(400, "Current password is incorrect.")
    verdict = evaluate_password(body.new_password, cu.user.email, cu.user.full_name)
    if not verdict["ok"]:
        raise HTTPException(422, {"message": "Password does not meet the policy.", "problems": verdict["problems"]})
    cu.user.password_hash = crypto.hash_password(body.new_password)
    cu.user.password_changed_at = utcnow()
    n = svc.revoke_all_sessions(db, cu.id, "PASSWORD_CHANGED", except_id=cu.session.id)
    audit.record(db, cu.actor, "AUTH_PASSWORD_CHANGED", target_type="USER", target_id=cu.id,
                 new_state={"other_sessions_revoked": n})
    db.commit()
    return {"ok": True, "other_sessions_revoked": n}


# ---- MFA management
@router.get("/mfa")
def mfa_status(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    creds = db.execute(select(MfaCredential).where(MfaCredential.user_id == cu.id)).scalars().all()
    return {
        "totp_enabled": any(c.kind == "TOTP" and c.confirmed for c in creds),
        "backup_codes_remaining": sum(1 for c in creds if c.kind == "BACKUP_CODE" and c.used_at is None),
        "email_otp": True,
        "sms": {"available": False, "note": "SMS provider adapter is integration-ready; configure in production."},
    }


@router.post("/mfa/totp/setup")
def totp_setup(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.start_totp_enrolment(db, cu.user)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/totp/confirm")
def totp_confirm(body: CodeIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        codes = svc.confirm_totp_enrolment(db, cu.user, body.code)
    except svc.AuthError as e:
        return _err(e)
    return {"enabled": True, "backup_codes": codes}


@router.post("/mfa/backup-codes")
def regen_backup(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    codes = svc.generate_backup_codes(db, cu.user)
    audit.record(db, cu.actor, "AUTH_BACKUP_CODES_REGENERATED", target_type="USER", target_id=cu.id)
    db.commit()
    return {"backup_codes": codes}


# ---- sessions
@router.get("/sessions")
def sessions(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(UserSession).where(UserSession.user_id == cu.id, UserSession.revoked_at.is_(None),
                                                UserSession.expires_at > utcnow())
                      .order_by(UserSession.last_seen_at.desc())).scalars().all()
    return [{"id": r.id, "ip": r.ip, "user_agent": r.user_agent, "created_at": r.created_at,
             "last_seen_at": r.last_seen_at, "mfa_method": r.mfa_method, "current": r.id == cu.session.id}
            for r in rows]


@router.delete("/sessions/{session_id}")
def revoke(session_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.get(UserSession, session_id)
    if not sess or sess.user_id != cu.id:
        raise HTTPException(404, "Session not found")
    svc.revoke_session(db, sess, "USER_REVOKED")
    audit.record(db, cu.actor, "AUTH_SESSION_REVOKED", target_type="SESSION", target_id=session_id)
    db.commit()
    return {"ok": True}


# ---- development-only simulated mailbox
@router.get("/dev/outbox")
def dev_outbox(email: str, db: Session = Depends(get_db)):
    if not get_settings().expose_dev_outbox or get_settings().is_production:
        raise HTTPException(404, "Not found")
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    recipients = [email.lower()] + ([user.phone] if user and user.phone else [])
    rows = db.execute(select(DevOutbox).where(DevOutbox.recipient.in_(recipients))
                      .order_by(DevOutbox.id.desc()).limit(10)).scalars().all()
    return [{"channel": r.channel, "to": r.recipient, "subject": r.subject, "body": r.body, "at": r.created_at}
            for r in rows]
