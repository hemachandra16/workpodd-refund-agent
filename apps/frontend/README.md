# WORPODD Refund Agent — Frontend

Next.js (App Router) + TypeScript + Tailwind UI for the customer chat surface
and the admin reasoning-log dashboard.

## Design system
Minimalism + neobrutalist structure:
- Hard 1px borders, ~2px radius, bold display type
- JetBrains Mono for IDs / money / timestamps / logs
- Single forest-green accent (`#14532D` light / `#2E8B57` dark)
- No gradients, no soft shadows, no emoji
- Light + dark + system via `next-themes`

Tokens live in `app/globals.css` (`:root` / `.dark`); Tailwind maps them in
`tailwind.config.ts`.

## Setup
```bash
cd apps/frontend
npm install
copy .env.example .env
npm run dev
```

API calls are proxied through `/api/*` → backend (see `next.config.mjs`) so the
`GROQ_API_KEY` stays strictly server-side.

## Routes
- `/` — landing
- `/chat` — customer chat + mic (Phase 6)
- `/admin` — live reasoning logs + decisions (Phase 7)
