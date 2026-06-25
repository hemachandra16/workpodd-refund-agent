"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

type SessionSummary = {
  session_id: string;
  latest_event_id: number;
  latest_summary: string;
  latest_status: string;
  latest_tool: string;
  event_count: number;
  created_at: string | null;
};

type ReasoningEvent = {
  id?: number;
  sequence?: number;
  session_id?: string;
  node: string;
  phase: string;
  status: string;
  summary: string;
  attempt: number;
  tool_called?: string;
  tool_args?: Record<string, unknown>;
  tool_result_summary?: string;
  duration_ms?: number;
  timestamp?: string;
};

type AuthState = "checking" | "locked" | "ready";

function railDot(status: string) {
  if (status === "failed") return "rail-dot rail-dot-failed";
  if (status === "retry" || status === "fallback") return "rail-dot rail-dot-retry";
  return "rail-dot rail-dot-ok";
}

function statusChip(status: string) {
  if (status === "failed") return "chip chip-deny";
  if (status === "retry" || status === "fallback") return "chip chip-review";
  return "chip chip-approval";
}

function EventTimeline({ events }: { events: ReasoningEvent[] }) {
  return (
    <div className="clause-rail space-y-3">
      {events.length === 0 ? (
        <div className="ml-9 rounded-md border border-dashed border-line bg-surface p-4 text-sm text-muted">
          No events selected.
        </div>
      ) : (
        events.map((event, index) => (
          <div key={`${event.id}-${index}`} className="grid grid-cols-[1.25rem_1fr] gap-4">
            <span className={railDot(event.status)} aria-hidden="true" />
            <article className="panel p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className={statusChip(event.status)}>{event.status}</span>
                <span className="chip">{event.node}</span>
                {event.tool_called ? <span className="chip">{event.tool_called}</span> : null}
                {event.attempt > 1 ? <span className="chip chip-review">attempt {event.attempt}</span> : null}
                <span className="tnum text-xs text-muted">#{event.sequence ?? index + 1}</span>
              </div>
              <p className="mt-3 text-sm font-semibold text-ink">{event.summary}</p>
              {event.tool_result_summary ? (
                <p className="mt-1 text-xs leading-5 text-muted">{event.tool_result_summary}</p>
              ) : null}
              {event.tool_args ? (
                <pre className="mt-3 max-h-28 overflow-auto rounded-sm bg-surface-subtle p-3 text-xs text-muted">
                  {JSON.stringify(event.tool_args, null, 2)}
                </pre>
              ) : null}
            </article>
          </div>
        ))
      )}
    </div>
  );
}

export default function AdminPage() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [loginError, setLoginError] = useState("");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>("");
  const [events, setEvents] = useState<ReasoningEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const clauseRailRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => sessions.find((session) => session.session_id === selectedSession),
    [sessions, selectedSession],
  );

  useEffect(() => {
    checkAuth();
  }, []);

  useEffect(() => {
    if (auth !== "ready") return;
    loadSessions();
  }, [auth]);

  useEffect(() => {
    if (!selectedSession || auth !== "ready") return;
    loadEvents(selectedSession);
    clauseRailRef.current?.scrollTo({ top: 0 });
  }, [selectedSession, auth]);

  useEffect(() => {
    if (auth !== "ready") return;
    const source = new EventSource("/api/admin/events/stream");
    source.addEventListener("reasoning", (message) => {
      const event = JSON.parse((message as MessageEvent).data) as ReasoningEvent;
      setSessions((current) => {
        const existing = current.find((session) => session.session_id === event.session_id);
        if (!existing) {
          return [
            {
              session_id: event.session_id ?? "",
              latest_event_id: event.id ?? 0,
              latest_summary: event.summary,
              latest_status: event.status,
              latest_tool: event.tool_called ?? "",
              event_count: 1,
              created_at: event.timestamp ?? null,
            },
            ...current,
          ];
        }
        return current.map((session) =>
          session.session_id === event.session_id
            ? {
                ...session,
                latest_event_id: event.id ?? session.latest_event_id,
                latest_summary: event.summary,
                latest_status: event.status,
                latest_tool: event.tool_called ?? session.latest_tool,
                event_count: Math.max(session.event_count, event.sequence ?? session.event_count),
              }
            : session,
        );
      });
      if (event.session_id === selectedSession) {
        setEvents((current) => [...current, event]);
      }
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [auth, selectedSession]);

  async function checkAuth() {
    const response = await fetch("/api/admin/me");
    setAuth(response.ok ? "ready" : "locked");
  }

  async function login() {
    setLoginError("");
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      setLoginError("Login failed");
      return;
    }
    setAuth("ready");
  }

  async function loadSessions() {
    const response = await fetch("/api/admin/sessions");
    if (!response.ok) {
      setAuth("locked");
      return;
    }
    const payload = (await response.json()) as SessionSummary[];
    setSessions(payload);
    if (!selectedSession && payload.length) {
      setSelectedSession(payload[0].session_id);
    }
  }

  async function loadEvents(sessionId: string) {
    const response = await fetch(`/api/admin/sessions/${sessionId}/events`);
    if (response.ok) {
      setEvents((await response.json()) as ReasoningEvent[]);
    }
  }

  async function runRetryDemo() {
    setBusy(true);
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "Please refund WP 1020 for retry.case@example.com. It is unused.",
        force_fallback: true,
      }),
    });
    if (response.ok) {
      const payload = (await response.json()) as { session_id: string };
      await loadSessions();
      setSelectedSession(payload.session_id);
      await loadEvents(payload.session_id);
    }
    setBusy(false);
  }

  if (auth === "checking") {
    return (
      <main className="shell grid min-h-screen place-items-center px-5">
        <div className="panel p-6">
          <p className="label">Admin</p>
          <p className="mt-2 text-sm text-muted">Checking session</p>
        </div>
      </main>
    );
  }

  if (auth === "locked") {
    return (
      <main className="shell grid min-h-screen place-items-center px-5">
        <section className="panel w-full max-w-sm p-6 shadow-calm">
          <p className="label">Admin access</p>
          <h1 className="display mt-1 text-2xl font-semibold">Reasoning logs</h1>
          <form className="mt-6 space-y-3" onSubmit={(e) => { e.preventDefault(); login(); }}>
            <label className="block">
              <span className="label">Username</span>
              <input className="field mt-1" value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="block">
              <span className="label">Password</span>
              <input
                className="field mt-1"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {loginError ? <p className="text-sm text-deny">{loginError}</p> : null}
            <button className="btn btn-primary w-full" type="submit">
              Sign in
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="topbar sticky top-0 z-10">
        <div className="mx-auto flex max-w-content items-center justify-between px-5 py-4">
          <div>
            <p className="label">Admin dashboard</p>
            <h1 className="display text-xl font-semibold">Reasoning operations</h1>
          </div>
          <div className="flex items-center gap-3">
            <Link className="btn text-sm no-underline" href="/chat?demo=1">
              Chat
            </Link>
            <button className="btn btn-primary text-sm" type="button" onClick={runRetryDemo} disabled={busy}>
              {busy ? "Running" : "Retry demo"}
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-content gap-5 px-5 py-5 lg:grid-cols-[22rem_minmax(0,1fr)_20rem]">
        <section className="panel min-h-[calc(100vh-8.5rem)] overflow-hidden">
          <div className="border-b border-line p-4">
            <p className="label">Sessions</p>
            <h2 className="display text-lg font-semibold">Decision queue</h2>
          </div>
          <div className="max-h-[calc(100vh-13rem)] overflow-auto p-3">
            {sessions.length === 0 ? (
              <p className="p-3 text-sm text-muted">No sessions yet.</p>
            ) : (
              sessions.map((session) => (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => setSelectedSession(session.session_id)}
                  className={`mb-2 w-full rounded-md border p-3 text-left ${
                    selectedSession === session.session_id
                      ? "border-trust bg-surface-subtle"
                      : "border-line bg-surface"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="tnum truncate text-xs font-semibold">{session.session_id}</span>
                    <span className={statusChip(session.latest_status)}>{session.latest_status}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-muted">{session.latest_summary}</p>
                  <p className="tnum mt-2 text-xs text-muted">{session.event_count} events</p>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="panel min-h-[calc(100vh-8.5rem)] overflow-hidden">
          <div className="border-b border-line p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="label">Live reasoning</p>
                <h2 className="display text-lg font-semibold">Clause Rail</h2>
              </div>
              {selectedSession ? <span className="chip">{selectedSession}</span> : null}
            </div>
          </div>
          <div ref={clauseRailRef} className="max-h-[calc(100vh-13rem)] overflow-auto p-5">
            <EventTimeline events={events} />
          </div>
        </section>

        <aside className="space-y-5">
          <section className="panel p-5">
            <p className="label">Session context</p>
            <h2 className="display mt-1 text-lg font-semibold">{selected?.latest_status ?? "No session"}</h2>
            <dl className="mt-5 space-y-4">
              <div>
                <dt className="label">Latest tool</dt>
                <dd className="tnum mt-1 text-sm">{selected?.latest_tool || "none"}</dd>
              </div>
              <div>
                <dt className="label">Latest event</dt>
                <dd className="tnum mt-1 text-sm">#{selected?.latest_event_id ?? "0"}</dd>
              </div>
              <div>
                <dt className="label">Event count</dt>
                <dd className="tnum mt-1 text-sm">{events.length}</dd>
              </div>
            </dl>
          </section>

          <section className="panel p-5">
            <p className="label">Retry markers</p>
            <div className="mt-3 space-y-2">
              {events
                .filter((event) => event.status === "failed" || event.status === "retry")
                .map((event, index) => (
                  <div key={`${event.sequence}-${index}`} className="panel-subtle p-3">
                    <span className={statusChip(event.status)}>{event.status}</span>
                    <p className="mt-2 text-sm font-medium">{event.tool_called || event.node}</p>
                    <p className="mt-1 text-xs text-muted">{event.tool_result_summary || event.summary}</p>
                  </div>
                ))}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
