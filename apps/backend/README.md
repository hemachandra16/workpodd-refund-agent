# WORPODD Backend

FastAPI backend for the WORPODD refund agent.

## What Runs Here

- `POST /chat`: typed customer refund request
- `POST /chat/stream`: SSE stream with reasoning events plus final answer
- `POST /voice`: multipart audio -> Whisper transcript -> same agent path -> Groq speech
- `WS /voice/ws`: WebSocket voice turn endpoint
- `POST /admin/login`: admin cookie login
- `GET /admin/sessions`: recent reasoning sessions
- `GET /admin/sessions/{session_id}/events`: append-only event trace
- `GET /admin/events/stream`: admin SSE feed

## Agent Flow

```text
guard -> agent -> tools -> agent -> done
```

The guard checks raw typed or transcribed voice input before it reaches the
model. The model can request tools, but action tools are blocked until
`check_refund_policy` has produced a verdict for the same order in the same
trace.

## Voice

Voice uses the same `run_agent` entrypoint as typed chat. The only extra steps
are:

1. Transcribe audio with Groq `whisper-large-v3-turbo`.
2. Run the transcript through the shared guard, agent loop, tools, and policy gate.
3. Synthesize the final response with Groq TTS when speech generation is available.

If TTS is unavailable, the route still returns the text response and reasoning log.

## Security

- Strict CORS from `FRONTEND_ORIGIN`; no wildcard origin.
- Chat, voice, and admin limits come from `.env`.
- Secrets are redacted before reasoning events are persisted.
- Reasoning event routes are read-only.
- Admin auth uses bcrypt plus signed cookies.
- Production boot fails if required secrets are missing or placeholders.

## Local Commands

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip_audit
uvicorn app.main:app --reload
```
