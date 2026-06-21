"""Groq voice helpers for Whisper STT and speech output."""

from __future__ import annotations

import base64
import io
from typing import Any

import httpx
from groq import Groq

from app.config import get_settings


class VoiceUnavailableError(RuntimeError):
    """Raised when voice transcription cannot run."""


def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str = "refund-request.webm",
    content_type: str = "audio/webm",
) -> str:
    """Transcribe speech with Groq Whisper."""
    settings = get_settings()
    if not settings.groq_available:
        raise VoiceUnavailableError("groq_api_key_unavailable")
    if not audio_bytes:
        raise VoiceUnavailableError("empty_audio")

    client = Groq(api_key=settings.groq_api_key)
    transcription = client.audio.transcriptions.create(
        model=settings.groq_stt_model,
        file=(filename, io.BytesIO(audio_bytes), content_type),
    )
    text = getattr(transcription, "text", "")
    if not text and isinstance(transcription, dict):
        text = str(transcription.get("text", ""))
    text = text.strip()
    if not text:
        raise VoiceUnavailableError("empty_transcript")
    return text


def synthesize_speech(text: str) -> tuple[str | None, str | None]:
    """Create a spoken reply with Groq TTS.

    The installed Groq SDK version in this project does not expose speech yet,
    so this uses Groq's OpenAI-compatible audio/speech REST endpoint directly.
    If TTS is unavailable, the caller can still return the text answer.
    """
    settings = get_settings()
    if not settings.groq_available or not text.strip():
        return None, None

    candidates = [(settings.groq_tts_model, settings.groq_tts_voice)]
    if settings.groq_tts_model == "playai-tts":
        candidates.append(("canopylabs/orpheus-v1-english", "troy"))

    response: httpx.Response | None = None
    for model, voice in candidates:
        payload: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "wav",
        }
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            break
        except Exception:
            response = None

    if response is None:
        return None, None

    return base64.b64encode(response.content).decode("ascii"), "audio/wav"
