"""Voice routes: Whisper transcription, shared agent execution, PlayAI speech."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi import WebSocketDisconnect, status
from pydantic import BaseModel

from app.agent.graph import run_agent
from app.config import get_settings
from app.db import SessionLocal
from app.routes.chat import persist_reasoning_event
from app.security.rate_limit import enforce_rate_limit, enforce_ws_rate_limit
from app.voice.service import VoiceUnavailableError, synthesize_speech, transcribe_audio

router = APIRouter(tags=["voice"])


class VoiceResponse(BaseModel):
    session_id: str
    transcript: str
    response: str
    verdict: str | None
    refund_cents: int
    clauses_hit: list[str]
    reasoning_log: list[dict[str, Any]]
    audio_base64: str | None = None
    audio_mime: str | None = None


def voice_rate_limit(request: Request) -> None:
    enforce_rate_limit("voice", request)


def _dev_transcript_override(transcript_override: str | None) -> str | None:
    settings = get_settings()
    if settings.is_production:
        return None
    transcript = (transcript_override or "").strip()
    return transcript or None


async def _read_audio(audio: UploadFile | None) -> tuple[bytes, str, str]:
    if audio is None:
        return b"", "refund-request.webm", "audio/webm"
    return (
        await audio.read(),
        audio.filename or "refund-request.webm",
        audio.content_type or "application/octet-stream",
    )


def _transcript_from_payload(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    transcript_override: str | None,
) -> str:
    override = _dev_transcript_override(transcript_override)
    if override:
        return override
    return transcribe_audio(audio_bytes, filename=filename, content_type=content_type)


def run_voice_turn(
    transcript: str,
    *,
    session_id: str | None = None,
    force_fallback: bool = False,
) -> VoiceResponse:
    """Run the exact same refund agent path used by typed chat."""
    resolved_session_id = session_id or f"session-{uuid.uuid4().hex[:12]}"
    persisted_events: list[dict[str, Any]] = []
    sequence = 0

    def sink(event: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        persisted_events.append(persist_reasoning_event(resolved_session_id, sequence, event))

    state = run_agent(
        transcript,
        metadata={"session_id": resolved_session_id, "channel": "voice"},
        session_factory=SessionLocal,
        force_fallback=force_fallback,
        event_sink=sink,
    )
    audio_base64, audio_mime = synthesize_speech(state.get("response_text", ""))
    return VoiceResponse(
        session_id=resolved_session_id,
        transcript=transcript,
        response=state.get("response_text", ""),
        verdict=state.get("verdict"),
        refund_cents=int(state.get("refund_cents", 0)),
        clauses_hit=list(state.get("clauses_hit") or []),
        reasoning_log=persisted_events or list(state.get("reasoning_log") or []),
        audio_base64=audio_base64,
        audio_mime=audio_mime,
    )


@router.post("/voice", response_model=VoiceResponse, dependencies=[Depends(voice_rate_limit)])
async def voice_turn(
    audio: UploadFile | None = File(default=None),
    session_id: str | None = Form(default=None),
    force_fallback: bool = Form(default=False),
    transcript_override: str | None = Form(default=None),
) -> VoiceResponse:
    audio_bytes, filename, content_type = await _read_audio(audio)
    try:
        transcript = _transcript_from_payload(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            transcript_override=transcript_override,
        )
    except VoiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return run_voice_turn(transcript, session_id=session_id, force_fallback=force_fallback)


@router.websocket("/voice/ws")
async def voice_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            try:
                enforce_ws_rate_limit("voice", websocket)
            except HTTPException:
                await websocket.send_json({"type": "error", "detail": "rate_limit_exceeded"})
                await websocket.close(code=1008)
                return

            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return

            payload: dict[str, Any] = {}
            audio_bytes = message.get("bytes") or b""
            filename = "refund-request.webm"
            content_type = "audio/webm"

            if message.get("text"):
                payload = json.loads(message["text"])
                if payload.get("audio_base64"):
                    audio_bytes = base64.b64decode(payload["audio_base64"])
                filename = payload.get("filename") or filename
                content_type = payload.get("content_type") or content_type

            try:
                transcript = _transcript_from_payload(
                    audio_bytes=audio_bytes,
                    filename=filename,
                    content_type=content_type,
                    transcript_override=payload.get("transcript_override"),
                )
                result = run_voice_turn(
                    transcript,
                    session_id=payload.get("session_id"),
                    force_fallback=bool(payload.get("force_fallback", False)),
                )
            except VoiceUnavailableError as exc:
                await websocket.send_json({"type": "error", "detail": str(exc)})
                continue

            await websocket.send_json({"type": "voice_result", **result.model_dump()})
    except WebSocketDisconnect:
        return
