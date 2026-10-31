"""Authentication service: credentials, MFA, brute-force defence, sessions, token rotation."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import Actor
from app.models import (
    DevOutbox,
    LoginAttempt,
    MfaCredential,
    OtpChallenge,
    RefreshToken,
    User,
    UserSession,
    utcnow,
)
from app.security import crypto, jwt_tokens, ratelimit
from app.services import audit
from app.services.notify import notify, raise_alert

GENERIC_LOGIN_ERROR = "Invalid email or password."
GENERIC_THROTTLE_ERROR = "Too many sign-in attempts. Please wait a few minutes and try again."
MAX_MFA_ATTEMPTS = 5


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401, code: str = "AUTH_FAILED", retry_after: int | None = None):
        super().__init__(message)
        self.message, self.status, self.code, self.retry_after = message, status, code, retry_after


# ------------------------------------------------------------------ CAPTCHA (integration-ready)
class CaptchaVerifier:
    """Plug a real provider (hCaptcha/Turnstile/reCAPTCHA) here. Local dev accepts everything."""

    def required(self, failures: int) -> bool:
        return failures >= 3

    def verify(self, token: str | None, ip: str) -> bool:
        return True


captcha = CaptchaVerifier()


# ------------------------------------------------------------------ simulated delivery
def deliver(db: Session, channel: str, recipient: str, subject: str, body: str) -> None:
    """Email/SMS delivery port. Local development writes to the dev outbox instead of sending.
    Swap this function for an SMTP / SES / Twilio adapter in production."""
    db.add(DevOutbox(channel=channel, recipient=recipient, subject=subject, body=body))


# ------------------------------------------------------------------ lockout (Redis, keyed by email)
def _ekey(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def lock_remaining(email: str) -> int:
    ttl = ratelimit.get_redis().ttl(f"astitva:lock:{_ekey(email)}")
    return max(0, int(ttl)) if ttl and ttl > 0 else 0


def recent_failures(email: str) -> int:
    s = get_settings()
    r = ratelimit.get_redis()
    key = f"astitva:fails:{_ekey(email)}"
    r.zremrangebyscore(key, 0, time.time() - s.login_failure_window_seconds)
    return int(r.zcard(key))


def register_failure(db: Session, email: str, user: User | None) -> int:
    """Records a failure. Returns lock seconds applied (0 if not locked).
    Lockouts are temporary with progressive cooldown (capped) so attackers cannot
    permanently deny service to a legitimate employee."""
    s = get_settings()
    r = ratelimit.get_redis()
    ek = _ekey(email)
    key = f"astitva:fails:{ek}"
    now = time.time()
    r.zadd(key, {f"{now}:{crypto.random_token(4)}": now})
    r.expire(key, s.login_failure_window_seconds)
    if recent_failures(email) < s.login_max_failures:
        return 0
    level = int(r.incr(f"astitva:locklvl:{ek}"))
    r.expire(f"astitva:locklvl:{ek}", 86400)
    seconds = min(s.lockout_max_seconds, s.lockout_base_seconds * (2 ** (level - 1)))
    r.set(f"astitva:lock:{ek}", "1", ex=seconds)
    r.delete(key)
    if user:
        user.locked_until = utcnow() + timedelta(seconds=seconds)
        user.lockout_level = level
        raise_alert(db, "MEDIUM" if level < 3 else "HIGH", "BRUTE_FORCE",
                    f"Account temporarily locked: {user.email}",
                    f"{s.login_max_failures} failed sign-in attempts within the window. "
                    f"Locked for {seconds}s (level {level}).", user_id=user.id,
                    details={"lock_seconds": seconds, "level": level})
        notify(db, user.id, "SUSPICIOUS_ACTIVITY", "Your account was temporarily locked",
               "Several failed sign-in attempts were detected. If this was not you, change your password.",
               "/settings", "WARNING")
        deliver(db, "EMAIL", user.email, "ASTITVA: account temporarily locked",
                f"We locked sign-in for {seconds // 60 or 1} minute(s) after repeated failed attempts.")
    return seconds


def clear_failures(email: str) -> None:
    ek = _ekey(email)
    r = ratelimit.get_redis()
    r.delete(f"astitva:fails:{ek}", f"astitva:locklvl:{ek}")


def _attempt(db: Session, email: str, user: User | None, ip: str, ua: str | None, success: bool,
             reason: str, stage: str = "PASSWORD") -> None:
    db.add(LoginAttempt(email=email.lower()[:255], user_id=user.id if user else None, ip=ip,
                        user_agent=(ua or "")[:255], success=success, reason=reason, stage=stage))


# ------------------------------------------------------------------ login step 1
@dataclass
class LoginResult:
    mfa_token: str
    methods: list[str]
    destination: str | None


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:2] + "•••@" + domain) if domain else "•••"


def start_login(db: Session, email: str, password: str, ip: str, ua: str | None,
                captcha_token: str | None = None) -> LoginResult:
    s = get_settings()
    email_n = email.strip().lower()

    bucket = ratelimit.check_login_buckets(ip, email_n)
    if not bucket.allowed:
        _attempt(db, email_n, None, ip, ua, False, "RATE_LIMITED")
        db.commit()
        raise AuthError(GENERIC_THROTTLE_ERROR, 429, "RATE_LIMITED", int(bucket.retry_after) + 1)

    locked = lock_remaining(email_n)
    if locked:
        user = db.execute(select(User).where(User.email == email_n)).scalar_one_or_none()
        _attempt(db, email_n, user, ip, ua, False, "LOCKED_OUT")
        db.commit()
        raise AuthError(GENERIC_THROTTLE_ERROR, 429, "LOCKED", locked)

    if captcha.required(recent_failures(email_n)) and not captcha.verify(captcha_token, ip):
        raise AuthError("Please complete the verification challenge.", 400, "CAPTCHA_REQUIRED")

    user = db.execute(select(User).where(User.email == email_n)).scalar_one_or_none()
    ok = crypto.verify_password(user.password_hash if user else None, password)
    if not ok or not user or user.status != "ACTIVE" or user.is_service_account:
        reason = "BAD_PASSWORD" if user else "UNKNOWN_ACCOUNT"
        if user and user.status != "ACTIVE":
            reason = "INACTIVE"
        _attempt(db, email_n, user, ip, ua, False, reason)
        lock = register_failure(db, email_n, user)
        distinct = ratelimit.track_distinct_accounts(ip, email_n)
        if distinct == s.stuffing_distinct_accounts_threshold:
            raise_alert(db, "HIGH", "CREDENTIAL_STUFFING", f"Possible credential stuffing from {ip}",
                        f"Failed sign-ins for {distinct} distinct accounts from one IP in 15 minutes. "
                        "IP rate limit tightened.", details={"ip": ip, "accounts": distinct})
        if distinct >= s.stuffing_distinct_accounts_threshold:
            ratelimit.take(f"login:ip:{ip}", s.ip_bucket_capacity, s.ip_bucket_refill_per_sec, cost=5)
        db.commit()
        if lock:
            raise AuthError(GENERIC_THROTTLE_ERROR, 429, "LOCKED", lock)
        raise AuthError(GENERIC_LOGIN_ERROR)

    if crypto.needs_rehash(user.password_hash):
        user.password_hash = crypto.hash_password(password)

    if not user.email_verified:
        _attempt(db, email_n, user, ip, ua, False, "EMAIL_NOT_VERIFIED")
        send_email_verification(db, user)
        db.commit()
        raise AuthError("Verify your email address first. We sent you a new code.", 403, "EMAIL_NOT_VERIFIED")

    _attempt(db, email_n, user, ip, ua, True, "PASSWORD_OK")
    methods = available_mfa_methods(db, user)
    challenge = OtpChallenge(user_id=user.id, purpose="LOGIN_MFA", ip=ip,
                             expires_at=utcnow() + timedelta(seconds=s.mfa_challenge_ttl_seconds))
    db.add(challenge)
    db.flush()
    destination = None
    if "TOTP" not in methods:
        destination = _send_login_otp(db, user, challenge)
    db.commit()
    return LoginResult(jwt_tokens.create_mfa_token(user.id, challenge.id), methods, destination)


def available_mfa_methods(db: Session, user: User) -> list[str]:
    creds = db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id,
                                                   MfaCredential.confirmed.is_(True))).scalars().all()
    kinds = {c.kind for c in creds if c.kind != "BACKUP_CODE" or c.used_at is None}
    methods = []
    if "TOTP" in kinds:
        methods.append("TOTP")
    methods.append("EMAIL")  # email OTP is always available as a fallback factor
    if "SMS" in kinds and user.phone:
        methods.append("SMS")
    if "BACKUP_CODE" in kinds:
        methods.append("BACKUP_CODE")
    return methods


def _send_login_otp(db: Session, user: User, challenge: OtpChallenge, channel: str = "EMAIL") -> str:
    code = crypto.numeric_code(6)
    challenge.code_hash = crypto.hash_otp(code)
    challenge.channel = channel
    if channel == "SMS" and user.phone:
        deliver(db, "SMS", user.phone, "ASTITVA sign-in code", f"Your ASTITVA sign-in code is {code}")
        return "SMS •••" + user.phone[-2:]
    deliver(db, "EMAIL", user.email, "Your ASTITVA sign-in code",
            f"Your one-time sign-in code is {code}. It expires in 5 minutes.")
    return mask_email(user.email)


def _load_challenge(db: Session, mfa_token: str) -> tuple[User, OtpChallenge]:
    try:
        claims = jwt_tokens.decode(mfa_token, "mfa_pending")
    except Exception:
        raise AuthError("Your sign-in session expired. Please sign in again.", 401, "MFA_EXPIRED")
    ch = db.get(OtpChallenge, claims["cid"])
    if (not ch or ch.purpose != "LOGIN_MFA" or ch.user_id != claims["sub"] or ch.consumed_at is not None
            or ch.expires_at < utcnow() or ch.attempts >= MAX_MFA_ATTEMPTS):
        raise AuthError("Your sign-in session expired. Please sign in again.", 401, "MFA_EXPIRED")
    user = db.get(User, ch.user_id)
    if not user or user.status != "ACTIVE":
        raise AuthError("Your sign-in session expired. Please sign in again.", 401, "MFA_EXPIRED")
    return user, ch


def resend_login_otp(db: Session, mfa_token: str, channel: str, ip: str) -> str:
    user, ch = _load_challenge(db, mfa_token)
    b = ratelimit.take(f"otp:resend:{user.id}", 3, 1 / 60)
    if not b.allowed:
        raise AuthError("Please wait before requesting another code.", 429, "RATE_LIMITED", int(b.retry_after) + 1)
    dest = _send_login_otp(db, user, ch, channel)
    db.commit()
    return dest


def verify_totp(db: Session, user: User, code: str) -> bool:
    cred = db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id, MfaCredential.kind == "TOTP",
                                                  MfaCredential.confirmed.is_(True))).scalar_one_or_none()
    if not cred or not code.isdigit():
        return False
    totp = pyotp.TOTP(crypto.decrypt(cred.secret_encrypted))
    now = time.time()
    for offset in (0, -1, 1):
        step = int(now // 30) + offset
        if totp.at(step * 30) == code:
            if cred.last_used_step is not None and step <= cred.last_used_step:
                return False  # replay of an already-used code
            cred.last_used_step = step
            cred.used_at = utcnow()
            return True
    return False


def verify_backup_code(db: Session, user: User, code: str) -> bool:
    normalized = code.replace("-", "").replace(" ", "").upper()
    creds = db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id,
                                                   MfaCredential.kind == "BACKUP_CODE",
                                                   MfaCredential.used_at.is_(None))).scalars().all()
    for c in creds:
        if crypto.verify_otp(c.code_hash, normalized):
            c.used_at = utcnow()
            return True
    return False


@dataclass
class SessionTokens:
    access_token: str
    refresh_token: str
    session: UserSession
    user: User


def complete_mfa(db: Session, mfa_token: str, method: str, code: str, ip: str, ua: str | None) -> SessionTokens:
    user, ch = _load_challenge(db, mfa_token)
    code = (code or "").strip()
    ok = False
    if method == "TOTP":
        ok = verify_totp(db, user, code)
    elif method in ("EMAIL", "SMS"):
        ok = ch.channel == method and crypto.verify_otp(ch.code_hash, code)
    elif method == "BACKUP_CODE":
        ok = verify_backup_code(db, user, code)
    if not ok:
        ch.attempts += 1
        _attempt(db, user.email, user, ip, ua, False, "MFA_FAILED", "MFA")
        lock = register_failure(db, user.email, user)
        if ch.attempts >= MAX_MFA_ATTEMPTS:
            ch.consumed_at = utcnow()
            raise_alert(db, "MEDIUM", "MFA_FAILURE", f"Repeated MFA failures for {user.email}",
                        "MFA challenge invalidated after too many incorrect codes.", user_id=user.id)
        db.commit()
        if lock:
            raise AuthError(GENERIC_THROTTLE_ERROR, 429, "LOCKED", lock)
        raise AuthError("Invalid verification code.", 401, "MFA_INVALID")

    ch.consumed_at = utcnow()
    _attempt(db, user.email, user, ip, ua, True, "MFA_OK", "MFA")
    clear_failures(user.email)
    user.locked_until = None
    user.lockout_level = 0
    _detect_suspicious_login(db, user, ip, ua)
    tokens = create_session(db, user, ip, ua, method)
    audit.record(db, Actor(user=user, ip=ip, user_agent=ua), "AUTH_LOGIN_SUCCESS", target_type="USER",
                 target_id=user.id, new_state={"mfa_method": method, "session_id": tokens.session.id})
    db.commit()
    return tokens


def _detect_suspicious_login(db: Session, user: User, ip: str, ua: str | None) -> None:
    previous = db.execute(
        select(LoginAttempt.ip).where(LoginAttempt.user_id == user.id, LoginAttempt.success.is_(True),
                                      LoginAttempt.stage == "MFA").distinct().limit(50)
    ).scalars().all()
    recent_fail = db.execute(
        select(LoginAttempt).where(LoginAttempt.user_id == user.id, LoginAttempt.success.is_(False),
                                   LoginAttempt.created_at > utcnow() - timedelta(hours=1))
    ).scalars().all()
    reasons = []
    if previous and ip not in previous:
        reasons.append(f"new IP address {ip}")
    if len(recent_fail) >= 3:
        reasons.append(f"{len(recent_fail)} failed attempts in the last hour")
    if reasons:
        raise_alert(db, "LOW" if len(reasons) == 1 else "MEDIUM", "SUSPICIOUS_LOGIN",
                    f"Unusual sign-in for {user.full_name}", "Successful sign-in with " + " and ".join(reasons) + ".",
                    user_id=user.id, details={"ip": ip, "user_agent": ua})
        notify(db, user.id, "SUSPICIOUS_ACTIVITY", "New sign-in to your account",
               "Signed in with " + " and ".join(reasons) + ". If this was not you, revoke the session in Settings.",
               "/settings", "WARNING")


# ------------------------------------------------------------------ sessions & refresh rotation
def create_session(db: Session, user: User, ip: str, ua: str | None, mfa_method: str | None) -> SessionTokens:
    s = get_settings()
    sess = UserSession(user_id=user.id, ip=ip, user_agent=(ua or "")[:255], mfa_method=mfa_method,
                       expires_at=utcnow() + timedelta(seconds=s.refresh_token_ttl_seconds))
    db.add(sess)
    db.flush()
    refresh = crypto.random_token(48)
    db.add(RefreshToken(session_id=sess.id, token_hash=crypto.token_digest(refresh),
                        expires_at=sess.expires_at))
    access = jwt_tokens.create_access_token(user.id, sess.id, user.role_names)
    return SessionTokens(access, refresh, sess, user)


def rotate_refresh(db: Session, refresh_token: str, ip: str, ua: str | None) -> SessionTokens:
    rt = db.execute(select(RefreshToken).where(RefreshToken.token_hash == crypto.token_digest(refresh_token))
                    ).scalar_one_or_none()
    if not rt:
        raise AuthError("Session expired. Please sign in again.", 401, "REFRESH_INVALID")
    sess = db.get(UserSession, rt.session_id)
    user = db.get(User, sess.user_id) if sess else None
    now = utcnow()
    if rt.used_at is not None:
        # Reuse of a rotated refresh token => likely theft. Kill the whole session.
        if sess and sess.revoked_at is None:
            sess.revoked_at = now
            sess.revoke_reason = "REFRESH_REUSE"
            raise_alert(db, "HIGH", "TOKEN_REUSE", "Refresh token reuse detected",
                        f"A previously rotated refresh token was presented for {user.email if user else 'unknown'}. "
                        "Session revoked.", user_id=user.id if user else None)
        db.commit()
        raise AuthError("Session expired. Please sign in again.", 401, "REFRESH_REUSED")
    if not sess or sess.revoked_at or rt.expires_at < now or not user or user.status != "ACTIVE":
        raise AuthError("Session expired. Please sign in again.", 401, "REFRESH_INVALID")
    rt.used_at = now
    new_refresh = crypto.random_token(48)
    db.add(RefreshToken(session_id=sess.id, token_hash=crypto.token_digest(new_refresh), expires_at=sess.expires_at))
    sess.last_seen_at = now
    access = jwt_tokens.create_access_token(user.id, sess.id, user.role_names)
    db.commit()
    return SessionTokens(access, new_refresh, sess, user)


def revoke_session(db: Session, sess: UserSession, reason: str) -> None:
    if sess.revoked_at is None:
        sess.revoked_at = utcnow()
        sess.revoke_reason = reason


def revoke_all_sessions(db: Session, user_id: str, reason: str, except_id: str | None = None) -> int:
    rows = db.execute(select(UserSession).where(UserSession.user_id == user_id,
                                                UserSession.revoked_at.is_(None))).scalars().all()
    n = 0
    for r in rows:
        if r.id != except_id:
            revoke_session(db, r, reason)
            n += 1
    return n


# ------------------------------------------------------------------ registration / verification / reset
def send_email_verification(db: Session, user: User) -> None:
    s = get_settings()
    code = crypto.numeric_code(6)
    db.add(OtpChallenge(user_id=user.id, purpose="EMAIL_VERIFY", channel="EMAIL", code_hash=crypto.hash_otp(code),
                        expires_at=utcnow() + timedelta(seconds=s.otp_ttl_seconds)))
    deliver(db, "EMAIL", user.email, "Verify your ASTITVA account", f"Your email verification code is {code}.")


def verify_email(db: Session, email: str, code: str) -> bool:
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if not user:
        return False
    b = ratelimit.take(f"verify:{user.id}", 5, 5 / 600)
    if not b.allowed:
        raise AuthError("Too many attempts. Try again later.", 429, "RATE_LIMITED", int(b.retry_after) + 1)
    chs = db.execute(select(OtpChallenge).where(OtpChallenge.user_id == user.id, OtpChallenge.purpose == "EMAIL_VERIFY",
                                                OtpChallenge.consumed_at.is_(None), OtpChallenge.expires_at > utcnow())
                     ).scalars().all()
    for ch in chs:
        if crypto.verify_otp(ch.code_hash, code.strip()):
            ch.consumed_at = utcnow()
            user.email_verified = True
            audit.record(db, Actor(user=user), "AUTH_EMAIL_VERIFIED", target_type="USER", target_id=user.id)
            db.commit()
            return True
    return False


def request_password_reset(db: Session, email: str, ip: str) -> None:
    b = ratelimit.take(f"reset:ip:{ip}", 5, 5 / 900)
    if not b.allowed:
        return  # silently drop; response stays generic
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if not user or user.status != "ACTIVE":
        return
    secret = crypto.random_token(32)
    ch = OtpChallenge(user_id=user.id, purpose="PASSWORD_RESET", channel="EMAIL", code_hash=crypto.token_digest(secret),
                      ip=ip, expires_at=utcnow() + timedelta(minutes=30))
    db.add(ch)
    db.flush()
    token = f"{ch.id}.{secret}"
    deliver(db, "EMAIL", user.email, "Reset your ASTITVA password",
            f"Use this link within 30 minutes: /reset-password?token={token}")
    db.commit()


def reset_password(db: Session, token: str, new_password: str, ip: str) -> User:
    from app.security.password_policy import evaluate_password

    cid, _, secret = token.partition(".")
    ch = db.get(OtpChallenge, cid) if cid else None
    if (not ch or ch.purpose != "PASSWORD_RESET" or ch.consumed_at or ch.expires_at < utcnow()
            or ch.code_hash != crypto.token_digest(secret)):
        raise AuthError("This reset link is invalid or has expired.", 400, "RESET_INVALID")
    user = db.get(User, ch.user_id)
    verdict = evaluate_password(new_password, user.email, user.full_name)
    if not verdict["ok"]:
        raise AuthError(" ".join(verdict["problems"]), 422, "WEAK_PASSWORD")
    ch.consumed_at = utcnow()
    user.password_hash = crypto.hash_password(new_password)
    user.password_changed_at = utcnow()
    n = revoke_all_sessions(db, user.id, "PASSWORD_RESET")
    clear_failures(user.email)
    ratelimit.get_redis().delete(f"astitva:lock:{_ekey(user.email)}")
    audit.record(db, Actor(user=user, ip=ip), "AUTH_PASSWORD_RESET", target_type="USER", target_id=user.id,
                 new_state={"sessions_revoked": n})
    notify(db, user.id, "SECURITY", "Password changed", "Your password was reset and all sessions were signed out.",
           "/settings", "WARNING")
    db.commit()
    return user


# ------------------------------------------------------------------ MFA enrolment
def start_totp_enrolment(db: Session, user: User) -> dict:
    import segno

    for old in db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id, MfaCredential.kind == "TOTP",
                                                      MfaCredential.confirmed.is_(False))).scalars():
        db.delete(old)
    secret = pyotp.random_base32()
    db.add(MfaCredential(user_id=user.id, kind="TOTP", secret_encrypted=crypto.encrypt(secret), confirmed=False))
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="ASTITVA")
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, dark="#0b1020", light="#ffffff")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": qr}


def confirm_totp_enrolment(db: Session, user: User, code: str) -> list[str]:
    pending = db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id, MfaCredential.kind == "TOTP",
                                                     MfaCredential.confirmed.is_(False))
                         .order_by(MfaCredential.created_at.desc())).scalars().first()
    if not pending or not pyotp.TOTP(crypto.decrypt(pending.secret_encrypted)).verify(code.strip(), valid_window=1):
        raise AuthError("Invalid verification code.", 400, "MFA_INVALID")
    for old in db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id, MfaCredential.kind == "TOTP",
                                                      MfaCredential.confirmed.is_(True))).scalars():
        db.delete(old)
    pending.confirmed = True
    pending.last_used_step = int(time.time() // 30)
    user.mfa_enabled = True
    codes = generate_backup_codes(db, user)
    audit.record(db, Actor(user=user), "AUTH_MFA_TOTP_ENROLLED", target_type="USER", target_id=user.id)
    db.commit()
    return codes


def generate_backup_codes(db: Session, user: User, count: int = 10) -> list[str]:
    for old in db.execute(select(MfaCredential).where(MfaCredential.user_id == user.id,
                                                      MfaCredential.kind == "BACKUP_CODE")).scalars():
        db.delete(old)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    import secrets as _s

    codes = []
    for _ in range(count):
        raw = "".join(_s.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(MfaCredential(user_id=user.id, kind="BACKUP_CODE", code_hash=crypto.hash_otp(raw), confirmed=True))
    return codes
