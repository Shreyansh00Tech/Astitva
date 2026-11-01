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
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import Actor
from app.core.rbac import MANAGER, REQUESTER, RESOURCE_OWNER, RISK_REVIEWER, SECURITY_ADMIN
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
    try:
        r = httpx.get(doc["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"},
                      timeout=HTTP_TIMEOUT)
        return r.json() if r.status_code == 200 else {}
    except Exception:  # userinfo only adds optional claims; the ID token is already verified
        return {}


# NamoID role names (case-insensitive, "-", " " and "_" treated alike) -> ASTITVA roles
ROLE_ALIASES = {
    "requester": REQUESTER, "employee": REQUESTER,
    "manager": MANAGER, "team_manager": MANAGER, "approver": MANAGER,
    "risk_reviewer": RISK_REVIEWER, "reviewer": RISK_REVIEWER, "risk": RISK_REVIEWER,
    "resource_owner": RESOURCE_OWNER, "owner": RESOURCE_OWNER, "data_owner": RESOURCE_OWNER,
    "model_owner": RESOURCE_OWNER,
    "security_admin": SECURITY_ADMIN, "security_manager": SECURITY_ADMIN, "admin": SECURITY_ADMIN,
}
ROLE_CLAIM_KEYS = ("roles", "role", "groups", "org_roles", "organization_roles", "permissions")


def _dig(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _strings(value) -> list[str]:
    """Flatten a role claim: "a b", "a,b", ["a"], [{"name": "a"}], {"a": {...}} all work."""
    if value is None:
        return []
    if isinstance(value, str):
        return [v for v in value.replace(",", " ").split() if v]
    if isinstance(value, dict):
        return list(value.keys())
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for k in ("name", "key", "slug", "role", "id"):
                    if isinstance(item.get(k), str):
                        out.append(item[k])
                        break
                for k in ROLE_CLAIM_KEYS:  # e.g. organizations: [{"id": .., "roles": [..]}]
                    if k in item:
                        out.extend(_strings(item[k]))
    return out


def raw_role_claims(claims: dict) -> list[str]:
    """Collect role names NamoID sent, from a pinned claim or the common places providers use."""
    pinned = get_settings().namoid_roles_claim.strip()
    if pinned:
        return _strings(_dig(claims, pinned) if "." in pinned else claims.get(pinned))
    found: list[str] = []
    for key, value in claims.items():
        k = key.lower().rsplit("/", 1)[-1].rsplit(":", 1)[-1]  # namespaced claims like https://x/roles
        if k in ROLE_CLAIM_KEYS:
            found.extend(_strings(value))
        elif k in ("organizations", "organization", "orgs", "org", "app_metadata", "user_metadata", "metadata"):
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, dict):
                    for rk in ROLE_CLAIM_KEYS:
                        if rk in item:
                            found.extend(_strings(item[rk]))
    return found


def map_roles(names: list[str]) -> list[str]:
    out = set()
    for n in names:
        key = n.strip().lower().rsplit(":", 1)[-1].replace("-", "_").replace(" ", "_")
        key = key.removeprefix("astitva_")
        if key.upper() in (REQUESTER, MANAGER, RISK_REVIEWER, RESOURCE_OWNER, SECURITY_ADMIN):
            out.add(key.upper())
        elif key in ROLE_ALIASES:
            out.add(ROLE_ALIASES[key])
    return sorted(out)


def _sync_roles(db: Session, user: User, roles: list[str], ip: str) -> None:
    if not roles or sorted(user.role_names) == roles:
        return
    before = user.role_names
    user.roles = list(db.execute(select(Role).where(Role.name.in_(roles))).scalars())
    if MANAGER not in roles and REQUESTER in roles and not user.manager_id:
        _assign_default_manager(db, user)
    audit.record(db, Actor(user=user, ip=ip), "USER_ROLES_SYNCED_FROM_NAMOID", target_type="USER",
                 target_id=user.id, previous_state={"roles": before}, new_state={"roles": roles},
                 reason="Roles assigned in the NamoID Console")


def _assign_default_manager(db: Session, user: User) -> None:
    managers = [u for u in db.execute(select(User).where(User.status == "ACTIVE")).scalars()
                if MANAGER in u.role_names and u.id != user.id]
    if len(managers) == 1:
        user.manager_id = managers[0].id


def _user_map() -> dict[str, str]:
    out = {}
    for pair in get_settings().namoid_user_map.split(","):
        left, sep, right = pair.partition("=")
        if sep and left.strip() and right.strip():
            out[left.strip().lower()] = right.strip().lower()
    return out


TEST_IDENTIFIER = re.compile(r"^(?P<local>[^@+]+)\+namoid_test_[a-z0-9]+@test\.namoid\.in$")


def test_user_candidates(email: str) -> list[str]:
    """NamoID sandbox test users sign in with an identifier such as
    ``rahul.sharma.nexora.example+namoid_test_dj8x9mzm@test.namoid.in`` for the display email
    ``rahul.sharma@nexora.example``. The "@" became a ".", so every split point is a candidate;
    only one that matches an existing ASTITVA account is used."""
    m = TEST_IDENTIFIER.match(email)
    if not m:
        return []
    parts = m.group("local").split(".")
    return [".".join(parts[:i]) + "@" + ".".join(parts[i:]) for i in range(1, len(parts) - 1)]


def resolve_user(db: Session, email: str, name: str | None, ip: str, roles: list[str] | None = None) -> User:
    mapped = _user_map().get(email)
    user = None
    if mapped:
        user = db.execute(select(User).where(User.email == mapped)).scalar_one_or_none()
    if not user:
        for candidate in test_user_candidates(email):
            user = db.execute(select(User).where(User.email == candidate)).scalar_one_or_none()
            if user:
                break
    if not user:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
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
    roles = roles or [REQUESTER]
    user.roles = list(db.execute(select(Role).where(Role.name.in_(roles))).scalars())
    db.add(user)
    db.flush()
    if MANAGER not in roles:
        _assign_default_manager(db, user)
    audit.record(db, Actor(user=user, ip=ip), "AUTH_PROVISIONED_FROM_NAMOID", target_type="USER",
                 target_id=user.id, new_state={"roles": roles})
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
    if not claims.get("email") or not raw_role_claims(claims):
        info = _userinfo(doc, tokens.get("access_token", ""))
        if info.get("sub") == claims["sub"]:
            claims = {**info, **claims}
    email = (claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is False:
        raise AuthError("Your NamoID account needs a verified email address.", 403, "NAMOID_EMAIL")

    s = get_settings()
    namoid_roles = map_roles(raw_role_claims(claims)) if s.namoid_role_sync else []
    user = resolve_user(db, email, claims.get("name"), ip, namoid_roles)
    _sync_roles(db, user, namoid_roles, ip)
    _attempt(db, user.email, user, ip, ua, True, "NAMOID_OK", "NAMOID")
    _detect_suspicious_login(db, user, ip, ua)
    session = create_session(db, user, ip, ua, "NAMOID")
    audit.record(db, Actor(user=user, ip=ip, user_agent=ua), "AUTH_LOGIN_SUCCESS", target_type="USER",
                 target_id=user.id, new_state={"method": "NAMOID_HOSTED_AUTH", "namoid_sub": claims["sub"],
                                               "session_id": session.session.id,
                                               "roles_source": "NAMOID" if namoid_roles else "ASTITVA",
                                               "roles": user.role_names,
                                               # claim names only (no values) to help configure role mapping
                                               "namoid_claim_names": sorted(claims.keys())})
    db.commit()
    return session, flow["next"]
