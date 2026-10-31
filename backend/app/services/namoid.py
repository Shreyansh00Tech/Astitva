"""NamoID Hosted Auth: OpenID Connect Authorization Code flow with PKCE (S256).

ASTITVA sends its users to the NamoID hosted sign-in page, receives an authorization
code on its callback, exchanges it server-side, validates the ID token (signature via
JWKS, issuer, audience, expiry, nonce) and then starts its own application session.
NamoID tokens are never sent to the browser or stored.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import Actor
from app.core.rbac import MANAGER, REQUESTER
from app.models import Role, User, utcnow
from app.security import crypto, jwt_tokens
from app.services import audit
from app.services.auth import AuthError, SessionTokens, _attempt, _detect_suspicious_login, create_session

FLOW_TTL_SECONDS = 600
HTTP_TIMEOUT = 10.0
_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass
class NamoIdFlow:
    authorize_url: str
    flow_cookie: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def discovery() -> dict:
    s = get_settings()
    issuer = s.namoid_issuer.rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and cached[0] > time.time():
        return cached[1]
    r = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    doc = r.json()
    if doc.get("issuer", "").rstrip("/") != issuer:
        raise AuthError("NamoID configuration does not match the configured issuer.", 502, "NAMOID_CONFIG")
    _discovery_cache[issuer] = (time.time() + 3600, doc)
    return doc


def _jwks_client(uri: str) -> jwt.PyJWKClient:
    if uri not in _jwks_clients:
        _jwks_clients[uri] = jwt.PyJWKClient(uri, cache_keys=True, timeout=int(HTTP_TIMEOUT))
    return _jwks_clients[uri]


def safe_next(next_path: str | None) -> str:
    ok = (next_path and next_path.startswith("/") and not next_path.startswith("//") and "\\" not in next_path
          and len(next_path) <= 512 and all(c.isprintable() for c in next_path))
    return next_path if ok else "/"


def start(next_path: str | None = None) -> NamoIdFlow:
    s = get_settings()
    if not s.namoid_enabled:
        raise AuthError("NamoID sign-in is not configured.", 503, "NAMOID_DISABLED")
    doc = discovery()
    state, nonce, verifier = crypto.random_token(24), crypto.random_token(24), crypto.random_token(48)
    params = {
        "response_type": "code",
        "client_id": s.namoid_client_id,
        "redirect_uri": s.namoid_redirect_uri,
        "scope": s.namoid_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    # The flow secrets live in a short-lived signed, HttpOnly cookie bound to this browser.
    cookie = jwt_tokens._encode({"sub": "namoid", "typ": "namoid_flow", "state": state, "nonce": nonce,
                                 "cv": verifier, "next": safe_next(next_path)}, FLOW_TTL_SECONDS)
    return NamoIdFlow(f"{doc['authorization_endpoint']}?{urlencode(params)}", cookie)


def _exchange_code(doc: dict, code: str, verifier: str) -> dict:
    s = get_settings()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": s.namoid_redirect_uri,
            "code_verifier": verifier, "client_id": s.namoid_client_id}
    auth = (s.namoid_client_id, s.namoid_client_secret) if s.namoid_client_secret else None
    r = httpx.post(doc["token_endpoint"], data=data, auth=auth, timeout=HTTP_TIMEOUT,
                   headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise AuthError("NamoID did not accept the sign-in. Please try again.", 401, "NAMOID_TOKEN")
    return r.json()


def _validate_id_token(doc: dict, id_token: str, nonce: str) -> dict:
    s = get_settings()
    try:
        key = _jwks_client(doc["jwks_uri"]).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=s.namoid_client_id,
                            issuer=doc["issuer"], options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                            leeway=60)
    except Exception:
        raise AuthError("The NamoID identity token could not be verified.", 401, "NAMOID_ID_TOKEN")
    if claims.get("nonce") != nonce:
        raise AuthError("The NamoID identity token could not be verified.", 401, "NAMOID_NONCE")
    return claims


def _userinfo(doc: dict, access_token: str) -> dict:
    if not doc.get("userinfo_endpoint") or not access_token:
        return {}
    r = httpx.get(doc["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"},
                  timeout=HTTP_TIMEOUT)
    return r.json() if r.status_code == 200 else {}


def _user_map() -> dict[str, str]:
    out = {}
    for pair in get_settings().namoid_user_map.split(","):
        left, sep, right = pair.partition("=")
        if sep and left.strip() and right.strip():
            out[left.strip().lower()] = right.strip().lower()
    return out


def resolve_user(db: Session, email: str, name: str | None, ip: str) -> User:
    target = _user_map().get(email, email)
    user = db.execute(select(User).where(User.email == target)).scalar_one_or_none()
    if user:
        if user.status != "ACTIVE" or user.is_service_account:
            raise AuthError("This account cannot sign in.", 403, "NAMOID_ACCOUNT_INACTIVE")
        return user
    if not get_settings().namoid_auto_provision:
        raise AuthError("No ASTITVA account is linked to this NamoID identity.", 403, "NAMOID_NOT_LINKED")
    count = db.query(User).count()
    user = User(email=email, full_name=(name or email.split("@")[0])[:160], employee_id=f"NX-{9000 + count:05d}",
                # Unusable local password: this person signs in only through NamoID.
                password_hash=crypto.hash_password(crypto.random_token(32)),
                designation="New Joiner", email_verified=True, password_changed_at=utcnow())
    user.roles = [db.execute(select(Role).where(Role.name == REQUESTER)).scalar_one()]
    managers = [u for u in db.execute(select(User).where(User.status == "ACTIVE")).scalars() if MANAGER in u.role_names]
    if len(managers) == 1:
        user.manager_id = managers[0].id
    db.add(user)
    db.flush()
    audit.record(db, Actor(user=user, ip=ip), "AUTH_PROVISIONED_FROM_NAMOID", target_type="USER",
                 target_id=user.id, new_state={"roles": [REQUESTER]})
    return user


def complete(db: Session, flow_cookie: str | None, code: str | None, state: str | None, iss: str | None,
             ip: str, ua: str | None) -> tuple[SessionTokens, str]:
    try:
        flow = jwt_tokens.decode(flow_cookie or "", "namoid_flow")
    except Exception:
        raise AuthError("Your sign-in took too long or was started elsewhere. Please try again.", 400,
                        "NAMOID_STATE")
    if not state or not hmac.compare_digest(state, flow["state"]):
        raise AuthError("Your sign-in took too long or was started elsewhere. Please try again.", 400,
                        "NAMOID_STATE")
    if not code:
        raise AuthError("NamoID did not return an authorization code.", 400, "NAMOID_NO_CODE")
    doc = discovery()
    if iss and iss.rstrip("/") != doc["issuer"].rstrip("/"):  # RFC 9207 mix-up protection
        raise AuthError("Unexpected identity provider response.", 400, "NAMOID_ISSUER")

    tokens = _exchange_code(doc, code, flow["cv"])
    if not tokens.get("id_token"):
        raise AuthError("NamoID did not return an identity token.", 401, "NAMOID_ID_TOKEN")
    claims = _validate_id_token(doc, tokens["id_token"], flow["nonce"])
    if not claims.get("email"):
        info = _userinfo(doc, tokens.get("access_token", ""))
        if info.get("sub") == claims["sub"]:
            claims = {**info, **claims}
    email = (claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is False:
        raise AuthError("Your NamoID account needs a verified email address.", 403, "NAMOID_EMAIL")

    user = resolve_user(db, email, claims.get("name"), ip)
    _attempt(db, user.email, user, ip, ua, True, "NAMOID_OK", "NAMOID")
    _detect_suspicious_login(db, user, ip, ua)
    session = create_session(db, user, ip, ua, "NAMOID")
    audit.record(db, Actor(user=user, ip=ip, user_agent=ua), "AUTH_LOGIN_SUCCESS", target_type="USER",
                 target_id=user.id, new_state={"method": "NAMOID_HOSTED_AUTH", "namoid_sub": claims["sub"],
                                               "session_id": session.session.id})
    db.commit()
    return session, flow["next"]
