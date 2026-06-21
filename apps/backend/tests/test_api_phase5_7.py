"""API coverage for Phase 5 chat streaming and Phase 7 admin gating."""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_chat_persists_reasoning_events_and_admin_requires_login():
    client = TestClient(app)

    chat = client.post(
        "/chat",
        json={
            "message": "Please refund WP 1020 for retry.case@example.com. It is unused.",
            "force_fallback": True,
        },
    )
    assert chat.status_code == 200
    payload = chat.json()
    assert payload["verdict"] == "approved"
    assert payload["session_id"]

    anonymous = client.get(f"/admin/sessions/{payload['session_id']}/events")
    assert anonymous.status_code == 401

    login = client.post("/admin/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200

    events = client.get(f"/admin/sessions/{payload['session_id']}/events")
    assert events.status_code == 200
    event_payload = events.json()
    assert len(event_payload) >= 2
    get_order_events = [event for event in event_payload if event.get("tool_called") == "get_order"]
    assert [event["status"] for event in get_order_events] == ["failed", "retry"]

    sessions = client.get("/admin/sessions")
    assert sessions.status_code == 200
    assert any(item["session_id"] == payload["session_id"] for item in sessions.json())


def test_chat_stream_emits_reasoning_and_final_event():
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "message": "Refund WP-1002 for bruno.hale@example.com. It is unused.",
            "force_fallback": True,
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: reasoning" in body
    assert "event: final" in body
    assert "denied" in body
