# WORPODD Frontend

Next.js App Router UI for the refund workspace and admin dashboard.

## Routes

- `/chat`: customer chat, visible streaming work state, microphone controls
- `/admin`: login-gated reasoning dashboard and live event stream
- `/`: redirects users into the usable support workspace

## Chat UI

The chat page starts with a welcoming agent message. Typed messages use
`/api/chat/stream`, so the UI can show the current reasoning step while the
backend works. Voice messages use `/api/voice` and move through these states:

```text
idle -> recording -> transcribing -> agent responding -> speaking -> idle
```

All `/api/*` requests are proxied to FastAPI by `next.config.mjs`, keeping
`GROQ_API_KEY` server-side only.

## Local Commands

```powershell
cd apps/frontend
npm install
npm run dev
npm run build
npm audit --audit-level=high
```
