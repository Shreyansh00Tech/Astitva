"""The live push for a break-glass activation carries the beep hint, and only Security Managers get it."""
import json

import pytest
from sqlalchemy import select

from app.core.rbac import SECURITY_ADMIN
from app.models import Resource
from app.services.notify import CHANNEL, users_with_role

from tests.conftest import login, user_by_email


@pytest.fixture
def monitor_pub(monkeypatch):
    """Capture what the app publishes to Redis for the live WebSocket push."""
    from app.security import ratelimit

    sent = []
    monkeypatch.setattr(ratelimit.get_redis(), "publish", lambda ch, data: sent.append((ch, data)))
    return sent


def test_breakglass_beep_hint_only_for_security_manager(client, db, monitor_pub):
    eng = user_by_email(db, "priya.desai")
    dev = db.execute(select(Resource).where(Resource.code == "RES-ENG-002")).scalar_one()
    h = login(client, eng.email)
    r = client.post("/api/emergency", headers=h, json={
        "resource_id": dev.id, "permissions": ["READ"], "incident_ref": "INC-50991", "duration_minutes": 15,
        "justification": "Orders service outage: need to inspect the failing migration state right away."})
    assert r.status_code == 201, r.text
    msgs = [json.loads(data) for ch, data in monitor_pub if ch == CHANNEL]
    beeps = [m for m in msgs if m.get("event") == "alert:BREAKGLASS"]
    sec_ids = {u.id for u in users_with_role(db, SECURITY_ADMIN)}
    assert beeps and sec_ids
    assert {m["user_id"] for m in beeps} == sec_ids  # nobody else gets the beep hint
    assert len(beeps) == len(sec_ids)  # exactly one per Security Manager, never repeated
    client.post(f"/api/emergency/{r.json()['id']}/revoke", headers=login(client, "admin"), json={"reason": "test done"})
