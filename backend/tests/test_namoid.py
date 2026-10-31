"""NamoID Hosted Auth: authorization request, callback validation and session start (NamoID is mocked)."""
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.auth import NAMOID_FLOW_COOKIE
from app.core.config import get_settings
from app.services import namoid

ISSUER = "https://astitva-test.sandbox.namoid.example"
CLIENT_ID = "namoid_client_test_fake"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
DOC = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/oauth/authorize",
       "token_endpoint": f"{ISSUER}/v1/oauth/token", "userinfo_endpoint": f"{ISSUER}/v1/oauth/userinfo",
       "jwks_uri": f"{ISSUER}/v1/oauth/jwks.json"}


class _Key:
    def __init__(self, key):
        self.key = key


class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return _Key(KEY.public_key())


@pytest.fixture
def nid(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "namoid_issuer", ISSUER)
    monkeypatch.setattr(s, "namoid_client_id", CLIENT_ID)
    monkeypatch.setattr(s, "namoid_client_secret", "")
    monkeypatch.setattr(s, "namoid_user_map", "")
    monkeypatch.setattr(s, "namoid_auto_provision", True)
    monkeypatch.setattr(namoid, "discovery", lambda: DOC)
    monkeypatch.setattr(namoid, "_jwks_client", lambda uri: _Jwks())
    state = {"claims": {}, "key": KEY, "token_calls": []}

    def exchange(doc, code, verifier):
        state["token_calls"].append({"code": code, "verifier": verifier})
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "nid_user_1", "iat": now, "exp": now + 300,
                  "nonce": state["nonce"], "email": "priya.desai@nexora.example", "email_verified": True,
                  **state["claims"]}
        return {"id_token": jwt.encode(claims, state["key"], algorithm="RS256"), "access_token": "at"}

    monkeypatch.setattr(namoid, "_exchange_code", exchange)
    return state


def _start(client, nid, next_path="/requests"):
    r = client.get("/api/auth/namoid/login", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 303
    url = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    flow = r.cookies.get(NAMOID_FLOW_COOKIE)
    nid["nonce"] = q["nonce"]
    return q, flow


def _callback(client, flow, **params):
    client.cookies.clear()
    if flow:
        client.cookies.set(NAMOID_FLOW_COOKIE, flow, path="/api/auth/namoid")
    return client.get("/api/auth/namoid/callback", params=params, follow_redirects=False)


def test_authorize_request_uses_pkce_state_and_nonce(client, nid):
    q, flow = _start(client, nid)
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["state"] and q["nonce"] and "openid" in q["scope"].split()
    assert q["redirect_uri"].endswith("/api/auth/namoid/callback")
    assert flow  # flow secrets are in a signed HttpOnly cookie, not in the URL


def test_callback_signs_in_mapped_user_and_sets_session(client, nid):
    q, flow = _start(client, nid)
    r = _callback(client, flow, code="abc", state=q["state"], iss=ISSUER)
    assert r.status_code == 200 and "/requests" in r.text
    assert "astitva_access" in r.headers.get("set-cookie", "") or r.cookies
    # PKCE verifier sent on exchange matches the challenge sent to NamoID
    assert namoid.pkce_challenge(nid["token_calls"][0]["verifier"]) == q["code_challenge"]
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "priya.desai@nexora.example"
    assert "MANAGER" in me.json()["roles"]


def test_user_map_links_namoid_email_to_demo_persona(client, nid, monkeypatch):
    monkeypatch.setattr(get_settings(), "namoid_user_map", "meera.reviewer@gmail.example=admin@nexora.example")
    nid["claims"] = {"email": "Meera.Reviewer@gmail.example"}
    q, flow = _start(client, nid)
    assert _callback(client, flow, code="abc", state=q["state"]).status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "admin@nexora.example"


def test_wrong_state_is_rejected(client, nid):
    q, flow = _start(client, nid)
    r = _callback(client, flow, code="abc", state="forged")
    assert r.status_code == 303 and "namoid_error=NAMOID_STATE" in r.headers["location"]
    assert not nid["token_calls"]


def test_missing_flow_cookie_is_rejected(client, nid):
    q, _ = _start(client, nid)
    r = _callback(client, None, code="abc", state=q["state"])
    assert "namoid_error=NAMOID_STATE" in r.headers["location"]


def test_nonce_mismatch_is_rejected(client, nid):
    q, flow = _start(client, nid)
    nid["claims"] = {"nonce": "replayed"}
    r = _callback(client, flow, code="abc", state=q["state"])
    assert "namoid_error=NAMOID_NONCE" in r.headers["location"]


def test_bad_signature_wrong_audience_and_issuer_mixup_are_rejected(client, nid):
    q, flow = _start(client, nid)
    nid["key"] = OTHER_KEY
    assert "NAMOID_ID_TOKEN" in _callback(client, flow, code="a", state=q["state"]).headers["location"]
    nid["key"] = KEY
    q, flow = _start(client, nid)
    nid["claims"] = {"aud": "someone_else"}
    assert "NAMOID_ID_TOKEN" in _callback(client, flow, code="a", state=q["state"]).headers["location"]
    q, flow = _start(client, nid)
    r = _callback(client, flow, code="a", state=q["state"], iss="https://evil.example")
    assert "NAMOID_ISSUER" in r.headers["location"]


def test_unverified_email_is_rejected(client, nid):
    nid["claims"] = {"email_verified": False}
    q, flow = _start(client, nid)
    assert "NAMOID_EMAIL" in _callback(client, flow, code="a", state=q["state"]).headers["location"]


def test_unknown_user_is_provisioned_as_employee_only(client, nid):
    nid["claims"] = {"email": "new.joiner@gmail.example", "name": "New Joiner", "sub": "nid_new"}
    q, flow = _start(client, nid)
    assert _callback(client, flow, code="a", state=q["state"]).status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["email"] == "new.joiner@gmail.example" and me["roles"] == ["REQUESTER"]


def test_unknown_user_refused_when_auto_provision_off(client, nid, monkeypatch):
    monkeypatch.setattr(get_settings(), "namoid_auto_provision", False)
    nid["claims"] = {"email": "stranger@gmail.example"}
    q, flow = _start(client, nid)
    assert "NAMOID_NOT_LINKED" in _callback(client, flow, code="a", state=q["state"]).headers["location"]


def test_open_redirect_in_next_is_neutralised(client, nid):
    q, flow = _start(client, nid, next_path="//evil.example/x")
    r = _callback(client, flow, code="a", state=q["state"])
    assert "evil.example" not in r.text


def test_disabled_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "namoid_issuer", "")
    assert client.get("/api/auth/namoid/config").json() == {"enabled": False}
    r = client.get("/api/auth/namoid/login", follow_redirects=False)
    assert "NAMOID_DISABLED" in r.headers["location"]
