# WORPODD Refund Agent — Backend

FastAPI + LangGraph + Groq backend for an AI customer-support agent that
resolves or denies e-commerce refunds.

## Stack
- **Framework:** FastAPI (SSE streaming, WebSocket voice)
- **Agent:** LangGraph — deterministic policy engine is the final authority;
  the LLM only drafts language
- **LLM / Voice:** Groq single-key — `llama-3.3-70b-versatile` (reasoning + tools),
  Whisper Large V3 Turbo (STT), PlayAI Dialog (TTS)
- **DB:** SQLite via SQLAlchemy (parameterized queries only)
- **Auth:** bcrypt + signed session cookie (admin dashboard)

## Setup
```bash
cd apps/backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy ..\..\.env.example .env    # then fill in GROQ_API_KEY etc.
uvicorn app.main:app --reload
```

## Endpoints (Phase 1)
- `GET /health` — service + config status

## Endpoints (later phases)
- `POST /chat` (SSE) — customer refund conversation
- `GET /admin/logs` (SSE) — live agent reasoning stream
- `WS  /voice` — duplex voice session
- `POST /admin/login` — admin session

## Security posture
See `app/security/`. Deterministic policy engine, prompt-injection guard node,
Pydantic validation on every endpoint, strict CORS + CSP/HSTS, per-IP rate
limits, append-only audit log, refund idempotency keys.
