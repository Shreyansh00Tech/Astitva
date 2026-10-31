from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def _encode(claims: dict, ttl: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": now, "nbf": now, "exp": now + timedelta(seconds=ttl), "iss": "astitva"}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user_id: str, session_id: str, roles: list[str]) -> str:
    return _encode({"sub": user_id, "sid": session_id, "roles": roles, "typ": "access"}, get_settings().access_token_ttl_seconds)


def create_mfa_token(user_id: str, challenge_id: str) -> str:
    return _encode({"sub": user_id, "cid": challenge_id, "typ": "mfa_pending"}, get_settings().mfa_challenge_ttl_seconds)


def decode(token: str, expected_type: str) -> dict:
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer="astitva",
                        options={"require": ["exp", "sub", "typ"]})
    if claims.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return claims
