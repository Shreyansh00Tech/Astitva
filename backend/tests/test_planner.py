"""Personal planner: employees add tasks to their own calendar; items stay private to their owner."""
from datetime import datetime, timedelta, timezone

from tests.conftest import login

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _range(days_before=7, days_after=14):
    return {"start": (NOW - timedelta(days=days_before)).isoformat(), "end": (NOW + timedelta(days=days_after)).isoformat()}


def test_seeded_week_and_project_tasks(client):
    rahul = login(client, "rahul.sharma")
    r = client.get("/api/me/planner", headers=rahul, params=_range())
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(i["title"] == "Daily stand-up" for i in body["items"])
    assert {"items", "project_tasks"} <= body.keys()


def test_create_update_complete_delete(client):
    neha = login(client, "neha.gupta")
    start = NOW + timedelta(days=1)
    r = client.post("/api/me/planner", headers=neha, json={
        "title": "  Prepare audit evidence  ", "category": "DEADLINE", "priority": "HIGH",
        "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["title"] == "Prepare audit evidence" and item["done"] is False

    r = client.patch(f"/api/me/planner/{item['id']}", headers=neha, json={"done": True, "category": "WORK"})
    assert r.status_code == 200 and r.json()["done"] is True and r.json()["category"] == "WORK"

    titles = [i["title"] for i in client.get("/api/me/planner", headers=neha, params=_range()).json()["items"]]
    assert "Prepare audit evidence" in titles

    assert client.delete(f"/api/me/planner/{item['id']}", headers=neha).status_code == 204
    titles = [i["title"] for i in client.get("/api/me/planner", headers=neha, params=_range()).json()["items"]]
    assert "Prepare audit evidence" not in titles


def test_validation(client):
    kavya = login(client, "kavya.reddy")
    start = NOW + timedelta(days=2)
    bad = [
        {"title": "x", "start_at": start.isoformat(), "end_at": (start - timedelta(hours=1)).isoformat()},
        {"title": "   ", "start_at": start.isoformat(), "end_at": start.isoformat()},
        {"title": "x", "category": "PARTY", "start_at": start.isoformat(), "end_at": start.isoformat()},
        {"title": "x", "start_at": start.isoformat(), "end_at": (start + timedelta(days=40)).isoformat()},
    ]
    for b in bad:
        assert client.post("/api/me/planner", headers=kavya, json=b).status_code == 422, b
    item = client.post("/api/me/planner", headers=kavya, json={
        "title": "ok", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()}).json()
    r = client.patch(f"/api/me/planner/{item['id']}", headers=kavya, json={"end_at": (start - timedelta(hours=3)).isoformat()})
    assert r.status_code == 422
    r = client.get("/api/me/planner", headers=kavya, params={"start": NOW.isoformat(), "end": (NOW + timedelta(days=90)).isoformat()})
    assert r.status_code == 422


def test_items_are_private_to_their_owner(client):
    rahul = login(client, "rahul.sharma")
    start = NOW + timedelta(days=3)
    item = client.post("/api/me/planner", headers=rahul, json={
        "title": "Private note", "category": "PERSONAL",
        "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()}).json()
    for who in ("priya.desai", "admin", "kavya.reddy"):
        h = login(client, who)
        assert client.patch(f"/api/me/planner/{item['id']}", headers=h, json={"done": True}).status_code == 404
        assert client.delete(f"/api/me/planner/{item['id']}", headers=h).status_code == 404
        listed = client.get("/api/me/planner", headers=h, params=_range()).json()["items"]
        assert all(i["id"] != item["id"] for i in listed)
    assert client.get("/api/me/planner", headers={}, params=_range()).status_code == 401
