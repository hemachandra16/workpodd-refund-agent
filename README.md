# WORPODD — AI Customer Support Agent

A hands-on build for the WORPODD product vertical slice: an AI customer-support
agent that **resolves or denies e-commerce refunds** using an LLM-driven loop
with a deterministic policy engine as the final authority.

> Status: scaffolding (Phase 1). See the build plan in the project notes.

## What it does
- Resolves refund requests against a **strict 13-clause refund policy**
- Uses an LLM (Groq) to converse with the customer and gather context
- **Cannot be talked into approving a refund that violates a rule** — the
  deterministic policy engine computes the verdict; the LLM only drafts language
- Voice-enabled (Groq Whisper STT + PlayAI TTS)
- Streams structured reasoning steps to an admin dashboard in real time

## Architecture
```
internworkiee/
├─ apps/
│  ├─ backend/   FastAPI + LangGraph + Groq + SQLite
│  └─ frontend/  Next.js + TS + Tailwind (light/dark)
└─ README.md
```

See `apps/backend/README.md` and `apps/frontend/README.md` for details.

## Quickstart
```bash
# Backend
cd apps/backend
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
cp ../../.env.example .env      # fill in GROQ_API_KEY
uvicorn app.main:app --reload   # http://127.0.0.1:8000

# Frontend
cd apps/frontend
npm install
cp .env.example .env
npm run dev                     # http://localhost:3000
```

## Tech choices
| Concern | Choice | Why |
|---|---|---|
| Agent | LangGraph | Explicit state machine; reasoning is inspectable |
| LLM/Voice | Groq | One key for LLM + STT + TTS; fast inference |
| Policy authority | Deterministic Python engine | Un-hallucinable refund decisions |
| Backend | FastAPI | First-class SSE + WebSocket streaming |
| Frontend | Next.js + Tailwind | Light/dark, minimal, accessible |
| DB | SQLite | Zero-config, swappable later |

## Security
Secrets server-side only · deterministic policy engine as final authority ·
prompt-injection guard node · Pydantic validation everywhere · parameterized
SQL · bcrypt admin sessions · strict CORS/CSP/HSTS · rate limiting · append-only
audit log · refund idempotency.

## License
Prototype / interview artifact. All rights reserved.
