"""Internal messaging: employees and managers only, members-only conversations, unread counts and history."""
from sqlalchemy import select

from app.models import ChatMessage, ConversationParticipant
from tests.conftest import login, user_by_email


def _open(client, h, other_id):
    r = client.post("/api/messages/conversations", headers=h, json={"user_id": other_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_contacts_are_employees_and_managers_only(client, db):
    kavya = login(client, "kavya.reddy")
    names = {c["name"] for c in client.get("/api/messages/contacts", headers=kavya).json()}
    assert names == {"Priya Desai", "Rahul Sharma", "Neha Gupta"}  # no Meera (Security Manager), not herself
    found = client.get("/api/messages/contacts?q=rahul", headers=kavya).json()
    assert [c["name"] for c in found] == ["Rahul Sharma"] and found[0]["relation"] == "Teammate"
    priya = login(client, "priya.desai")
    rel = {c["name"]: c["relation"] for c in client.get("/api/messages/contacts", headers=priya).json()}
    assert rel == {"Kavya Reddy": "Your team", "Neha Gupta": "Your team", "Rahul Sharma": "Your team"}
    assert "messages:use" in client.get("/api/auth/me", headers=priya).json()["permissions"]


def test_security_manager_is_kept_out(client, db):
    meera_id = user_by_email(db, "admin").id
    admin = login(client, "admin")
    assert "messages:use" not in client.get("/api/auth/me", headers=admin).json()["permissions"]
    for path in ("/api/messages/contacts", "/api/messages/conversations", "/api/messages/unread"):
        assert client.get(path, headers=admin).status_code == 403
    rahul = login(client, "rahul.sharma")
    assert client.post("/api/messages/conversations", headers=rahul, json={"user_id": meera_id}).status_code == 404
    assert client.post("/api/messages/conversations", headers=rahul,
                       json={"user_id": user_by_email(db, "rahul.sharma").id}).status_code == 400


def test_chat_flow_unread_and_history(client, db):
    priya_id = user_by_email(db, "priya.desai").id
    neha_id = user_by_email(db, "neha.gupta").id
    neha = login(client, "neha.gupta")
    cid = _open(client, neha, priya_id)
    assert _open(client, neha, priya_id) == cid  # one conversation per pair
    for text in ("Hi Priya, quick question on the Q4 report", "Can we sync at 4?"):
        r = client.post(f"/api/messages/conversations/{cid}/messages", headers=neha, json={"body": text})
        assert r.status_code == 200 and r.json()["sender_id"] == neha_id and r.json()["created_at"]
    priya = login(client, "priya.desai")
    assert client.post("/api/messages/conversations", headers=priya, json={"user_id": neha_id}).json()["id"] == cid
    assert client.get("/api/messages/unread", headers=priya).json()["unread"] == 2
    conv = next(c for c in client.get("/api/messages/conversations", headers=priya).json() if c["id"] == cid)
    assert conv["unread"] == 2 and conv["contact"]["name"] == "Neha Gupta" and conv["last_message"]["body"] == "Can we sync at 4?"
    hist = client.get(f"/api/messages/conversations/{cid}", headers=priya).json()
    assert [m["body"] for m in hist["messages"]] == ["Hi Priya, quick question on the Q4 report", "Can we sync at 4?"]
    assert client.post(f"/api/messages/conversations/{cid}/read", headers=priya).status_code == 200
    assert client.get("/api/messages/unread", headers=priya).json()["unread"] == 0
    client.post(f"/api/messages/conversations/{cid}/messages", headers=priya, json={"body": "Sure, 4 works"})
    neha = login(client, "neha.gupta")
    assert next(c for c in client.get("/api/messages/conversations", headers=neha).json() if c["id"] == cid)["unread"] == 1
    db.expire_all()
    assert db.scalar(select(ChatMessage.body).where(ChatMessage.conversation_id == cid)
                     .order_by(ChatMessage.created_at.desc()).limit(1)) == "Sure, 4 works"


def test_only_members_can_read_or_write_a_conversation(client, db):
    rahul_id = user_by_email(db, "rahul.sharma").id
    kavya = login(client, "kavya.reddy")
    cid = _open(client, kavya, rahul_id)
    client.post(f"/api/messages/conversations/{cid}/messages", headers=kavya, json={"body": "private note"})
    neha = login(client, "neha.gupta")  # not a member
    assert client.get(f"/api/messages/conversations/{cid}", headers=neha).status_code == 404
    assert client.post(f"/api/messages/conversations/{cid}/messages", headers=neha, json={"body": "hi"}).status_code == 404
    assert client.post(f"/api/messages/conversations/{cid}/read", headers=neha).status_code == 404
    assert all(c["id"] != cid for c in client.get("/api/messages/conversations", headers=neha).json())
    priya = login(client, "priya.desai")  # being their manager does not open their private chat
    assert client.get(f"/api/messages/conversations/{cid}", headers=priya).status_code == 404
    admin = login(client, "admin")
    assert client.get(f"/api/messages/conversations/{cid}", headers=admin).status_code == 403
    db.expire_all()
    members = set(db.scalars(select(ConversationParticipant.user_id).where(ConversationParticipant.conversation_id == cid)))
    assert members == {rahul_id, user_by_email(db, "kavya.reddy").id}


def test_message_validation(client, db):
    rahul = login(client, "rahul.sharma")
    cid = _open(client, rahul, user_by_email(db, "neha.gupta").id)
    assert client.post(f"/api/messages/conversations/{cid}/messages", headers=rahul, json={"body": "   "}).status_code == 422
    assert client.post(f"/api/messages/conversations/{cid}/messages", headers=rahul, json={"body": "x" * 2001}).status_code == 422
