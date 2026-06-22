"""Customer chat routes wired to the dynamic refund agent."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import run_agent
from app.config import get_settings
from app.db import SessionLocal
from app.models import ReasoningEvent
from app.security.rate_limit import enforce_rate_limit

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    # Reject unexpected fields (mass-assignment defense): a request carrying
    # e.g. is_admin=true or refund_cents=99999 is refused with 422 rather than
    # silently accepted and ignored.
    model_config = {"extra": "forbid"}

    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=80)
    force_fallback: bool = False


class ChatResponse(BaseModel):
    session_id: str
    response: str
    verdict: str | None
    refund_cents: int
    clauses_hit: list[str]
    reasoning_log: list[dict[str, Any]]


def chat_rate_limit(request: Request) -> None:
    enforce_rate_limit("chat", request)


def _secret_values() -> list[str]:
    settings = get_settings()
    values = [
        settings.groq_api_key,
        settings.admin_session_secret,
        settings.admin_password_hash,
    ]
    return [value for value in values if value and len(value) >= 8]


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(event, default=str)
    for value in _secret_values():
        text = text.replace(value, "[REDACTED]")
    return json.loads(text)


def persist_reasoning_event(session_id: str, sequence: int, event: dict[str, Any]) -> dict[str, Any]:
    """Append one reasoning event to the DB and return the event with sequence/id."""
    event_with_sequence = redact_event(dict(event))
    event_with_sequence["sequence"] = sequence
    tool_args = event_with_sequence.get("tool_args", {})

    row = ReasoningEvent(
        session_id=session_id,
        sequence=sequence,
        node=str(event_with_sequence.get("node", "")),
        phase=str(event_with_sequence.get("phase", "")),
        status=str(event_with_sequence.get("status", "ok")),
        summary=str(event_with_sequence.get("summary", "")),
        tool_called=str(event_with_sequence.get("tool_called", "")),
        tool_args_json=json.dumps(tool_args, default=str),
        tool_result_summary=str(event_with_sequence.get("tool_result_summary", "")),
        event_json=json.dumps(event_with_sequence, default=str),
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        event_with_sequence["id"] = row.id
    return event_with_sequence


def serialize_state(session_id: str, state: dict) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        response=state.get("response_text", ""),
        verdict=state.get("verdict"),
        refund_cents=int(state.get("refund_cents", 0)),
        clauses_hit=list(state.get("clauses_hit") or []),
        reasoning_log=list(state.get("reasoning_log") or []),
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(chat_rate_limit)])
async def chat(request: ChatRequest) -> ChatResponse:
    sequence = 0

    def sink(event: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        persist_reasoning_event(session_id, sequence, event)

    session_id = request.session_id or f"session-{uuid.uuid4().hex[:12]}"
    state = run_agent(
        request.message,
        metadata={"session_id": session_id},
        session_factory=SessionLocal,
        force_fallback=request.force_fallback,
        event_sink=sink,
    )
    return serialize_state(session_id, state)


@router.post("/chat/stream", dependencies=[Depends(chat_rate_limit)])
async def chat_stream(request: ChatRequest):
    session_id = request.session_id or f"session-{uuid.uuid4().hex[:12]}"
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    sequence = 0

    def sink(event: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        persisted = persist_reasoning_event(session_id, sequence, event)
        events.put(persisted)

    def worker() -> None:
        try:
            state = run_agent(
                request.message,
                metadata={"session_id": session_id},
                session_factory=SessionLocal,
                force_fallback=request.force_fallback,
                event_sink=sink,
            )
            events.put({
                "type": "final",
                "session_id": session_id,
                "response": state.get("response_text", ""),
                "verdict": state.get("verdict"),
                "refund_cents": state.get("refund_cents", 0),
                "clauses_hit": state.get("clauses_hit", []),
            })
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator():
        while True:
            item = events.get()
            if item is None:
                break
            event_type = item.pop("type", "reasoning")
            yield {
                "event": event_type,
                "data": json.dumps(item, default=str),
            }

    return EventSourceResponse(event_generator())
