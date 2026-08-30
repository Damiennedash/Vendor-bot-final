import hashlib
import hmac
import json

from app.models import BotSession, ProcessedMessage


def _signed_headers(body):
    digest = hmac.new(b"test-meta-secret", body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + digest}


def test_rejects_invalid_signature(client):
    response = client.post("/webhook", json={"entry": []})
    assert response.status_code == 401


def test_ignores_status_notifications(client):
    payload = {"entry": [{"changes": [{"value": {"statuses": []}}]}]}
    body = json.dumps(payload).encode()
    response = client.post("/webhook", data=body, headers=_signed_headers(body))
    assert response.status_code == 200


def test_health_reports_database_connection(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["database"] == "connected"
    assert response.get_json()["database_provider"] == "local_or_custom"


def test_first_message_creates_persistent_session(client, monkeypatch):
    monkeypatch.setattr("app.whatsapp.send_message", lambda phone, reply: True)
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.1",
            "from": "22890000000",
            "type": "text",
            "text": {"body": "Bonjour"},
        }]}}]}]
    }
    body = json.dumps(payload).encode()
    response = client.post("/webhook", data=body, headers=_signed_headers(body))
    assert response.status_code == 200

    from app.extensions import db

    assert db.session.get(ProcessedMessage, "wamid.1") is not None
    session = db.session.get(BotSession, "22890000000")
    assert session is not None
    assert session.step == "nom"


def test_duplicate_message_is_not_processed_twice(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.whatsapp.send_message", lambda phone, reply: sent.append(reply))
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.duplicate",
            "from": "22891111111",
            "type": "text",
            "text": {"body": "Bonjour"},
        }]}}]}]
    }
    body = json.dumps(payload).encode()
    first = client.post("/webhook", data=body, headers=_signed_headers(body))
    second = client.post("/webhook", data=body, headers=_signed_headers(body))
    assert first.status_code == 200
    assert second.get_json()["status"] == "duplicate"
    assert len(sent) == 1
