import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/astitva_test")
os.environ["APP_ENV"] = "test"
os.environ["ENABLE_INPROCESS_SCHEDULER"] = "false"
os.environ["LLM_PROVIDER"] = "none"

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.security import ratelimit  # noqa: E402

FAKE = fakeredis.FakeRedis(decode_responses=True)
ratelimit.set_redis(FAKE)

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DevOutbox, User  # noqa: E402
from app.seed import DEMO_PASSWORD, DOMAIN, run  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    run(reset=True)
    set_routing(False)  # most scenario tests exercise the full Manager -> Security Manager chain
    yield


def set_routing(enabled: bool, auto: int = 30, manager_only: int = 60):
    """Turn the risk-based routing policy on/off directly in the DB (the API path is tested in test_routing)."""
    from app.models import Policy
    from app.services.workflow import ROUTING_POLICY_NAME

    with SessionLocal() as s:
        p = s.execute(select(Policy).where(Policy.name == ROUTING_POLICY_NAME)).scalar_one()
        p.enabled = enabled
        p.rules = {**p.rules, "auto_approve_max_score": auto, "manager_only_max_score": manager_only}
        s.commit()


@pytest.fixture(autouse=True)
def clean_redis():
    FAKE.flushall()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def latest_otp(addr: str) -> str:
    with SessionLocal() as s:
        import re

        for msg in s.execute(select(DevOutbox).where(DevOutbox.recipient == addr).order_by(DevOutbox.id.desc()).limit(10)).scalars():
            m = re.search(r"\b(\d{6})\b", msg.body)
            if m:
                return m.group(1)
        raise AssertionError(f"no OTP for {addr}")


def login(client: TestClient, local: str, password: str = DEMO_PASSWORD) -> dict:
    """Full real login: password -> email OTP from the simulated outbox -> MFA verify -> bearer token."""
    addr = email(local) if "@" not in local else local
    r = client.post("/api/auth/login", json={"email": addr, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    if "TOTP" in body["methods"]:  # use the email fallback factor (exercises /mfa/resend)
        rr = client.post("/api/auth/mfa/resend", json={"mfa_token": body["mfa_token"], "channel": "EMAIL"})
        assert rr.status_code == 200, rr.text
    code = latest_otp(addr)
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "method": "EMAIL", "code": code,
                                                  "return_tokens": True})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def user_by_email(db, local: str) -> User:
    return db.execute(select(User).where(User.email == email(local))).scalar_one()
