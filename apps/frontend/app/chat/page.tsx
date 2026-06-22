"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

type ReasoningEvent = {
  node: string;
  phase: string;
  status: "ok" | "failed" | "retry" | "fallback" | string;
  summary: string;
  attempt: number;
  tool_called?: string;
  tool_args?: Record<string, unknown>;
  tool_result_summary?: string;
  duration_ms?: number;
  timestamp?: string;
};

type ChatResponse = {
  session_id: string;
  response: string;
  verdict: string | null;
  refund_cents: number;
  clauses_hit: string[];
  reasoning_log: ReasoningEvent[];
};

type Message = {
  role: "customer" | "agent";
  content: string;
};

type VoiceState = "idle" | "recording" | "transcribing" | "agent responding" | "speaking";

const statusLabel: Record<string, string> = {
  approved: "Approved",
  approved_partial: "Partial",
  approved_store_credit: "Store credit",
  manual_review: "Review",
  denied: "Denied",
};

function verdictChip(verdict: string | null | undefined) {
  if (!verdict) return "chip";
  if (verdict === "denied") return "chip chip-deny";
  if (verdict === "manual_review") return "chip chip-review";
  return "chip chip-approval";
}

function railDot(status: string) {
  if (status === "failed") return "rail-dot rail-dot-failed";
  if (status === "retry" || status === "fallback") return "rail-dot rail-dot-retry";
  return "rail-dot rail-dot-ok";
}

function money(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

function Timeline({ events }: { events: ReasoningEvent[] }) {
  return (
    <div className="clause-rail space-y-3">
      {events.length === 0 ? (
        <div className="ml-9 rounded-md border border-dashed border-line bg-surface p-4 text-sm text-muted">
          No reasoning events yet.
        </div>
      ) : (
        events.map((event, index) => (
          <div key={`${event.timestamp}-${index}`} className="grid grid-cols-[1.25rem_1fr] gap-4">
            <span className={railDot(event.status)} aria-hidden="true" />
            <article className="panel p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip">{event.status}</span>
                {event.tool_called ? <span className="chip">{event.tool_called}</span> : null}
                {event.attempt > 1 ? <span className="chip chip-review">attempt {event.attempt}</span> : null}
                <span className="tnum text-xs text-muted">{event.duration_ms?.toFixed?.(1) ?? "0.0"} ms</span>
              </div>
              <p className="mt-2 text-sm font-medium text-ink">{event.summary}</p>
              {event.tool_result_summary ? (
                <p className="mt-1 text-xs text-muted">{event.tool_result_summary}</p>
              ) : null}
            </article>
          </div>
        ))
      )}
    </div>
  );
}

export default function ChatPage() {
  const [message, setMessage] = useState(
    "Please refund WP 1020 for retry.case@example.com. It is unused.",
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    { role: "agent", content: "Hi, how can I help with your refund today?" },
  ]);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [demoMode, setDemoMode] = useState(false);
  const [liveEvents, setLiveEvents] = useState<ReasoningEvent[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [recorder, setRecorder] = useState<MediaRecorder | null>(null);

  useEffect(() => {
    setDemoMode(new URLSearchParams(window.location.search).get("demo") === "1");
  }, []);

  const latestTool = useMemo(() => {
    const events = result?.reasoning_log ?? [];
    return [...events].reverse().find((event) => event.tool_called)?.tool_called ?? "none";
  }, [result]);

  async function submit() {
    const trimmed = message.trim();
    if (!trimmed || pending) return;
    setPending(true);
    setError("");
    setLiveEvents([]);
    setMessages((current) => [...current, { role: "customer", content: trimmed }]);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          session_id: sessionId,
          force_fallback: demoMode,
        }),
      });
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      await consumeChatStream(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  async function consumeChatStream(response: Response) {
    const reader = response.body?.getReader();
    if (!reader) throw new Error("Streaming response unavailable");
    const decoder = new TextDecoder();
    let buffer = "";
    const receivedEvents: ReasoningEvent[] = [];

    // Parse a single SSE frame into its event name + payload, applying it to
    // the right piece of UI state. Extracted so we can call it both inside the
    // read loop AND once more after the stream closes to drain any final frame
    // that didn't end with a trailing \n\n (the most common reason the agent's
    // reply never rendered: the `final` frame was the last thing in the stream
    // and sat unprocessed in the buffer when the reader signalled done).
    function processFrame(frame: string) {
      const lines = frame.split("\n");
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      const payload = JSON.parse(dataLines.join("\n"));

      if (eventName === "reasoning") {
        receivedEvents.push(payload as ReasoningEvent);
        setLiveEvents([...receivedEvents]);
      } else if (eventName === "final") {
        const finalPayload = payload as Omit<ChatResponse, "reasoning_log">;
        setSessionId(finalPayload.session_id);
        setResult({
          ...finalPayload,
          reasoning_log: receivedEvents,
        });
        setMessages((current) => [
          ...current,
          { role: "agent", content: finalPayload.response },
        ]);
      }
    }

    // Each SSE frame is separated by a blank line (\n\n). We accumulate bytes
    // into `buffer`, peel off complete frames, and keep the trailing partial
    // frame for the next read.
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      // Keep the last (possibly partial) chunk for the next iteration.
      buffer = frames.pop() ?? "";
      for (const frame of frames) processFrame(frame);
    }

    // Drain any final frame left in the buffer when the stream closed. Without
    // this, the agent's reply (the last `final` event) can be silently dropped
    // if it wasn't followed by a trailing blank line.
    const tail = buffer.trim();
    if (tail) processFrame(tail);
  }

  async function toggleRecording() {
    if (voiceState === "recording" && recorder) {
      recorder.stop();
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks: BlobPart[] = [];
    const nextRecorder = new MediaRecorder(stream);
    setRecorder(nextRecorder);
    setVoiceState("recording");

    nextRecorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    nextRecorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      setVoiceState("transcribing");
      const audio = new Blob(chunks, { type: nextRecorder.mimeType || "audio/webm" });
      const form = new FormData();
      form.append("audio", audio, "refund-request.webm");
      form.append("force_fallback", String(demoMode));
      if (sessionId) form.append("session_id", sessionId);
      try {
        const response = await fetch("/api/voice", { method: "POST", body: form });
        if (!response.ok) throw new Error(`Voice request failed: ${response.status}`);
        setVoiceState("agent responding");
        const payload = await response.json();
        setSessionId(payload.session_id);
        setLiveEvents(payload.reasoning_log ?? []);
        setResult({
          session_id: payload.session_id,
          response: payload.response,
          verdict: payload.verdict,
          refund_cents: payload.refund_cents,
          clauses_hit: payload.clauses_hit ?? [],
          reasoning_log: payload.reasoning_log ?? [],
        });
        setMessages((current) => [
          ...current,
          { role: "customer", content: payload.transcript },
          { role: "agent", content: payload.response },
        ]);
        if (payload.audio_base64) {
          setVoiceState("speaking");
          const audioElement = new Audio(`data:${payload.audio_mime};base64,${payload.audio_base64}`);
          audioElement.onended = () => setVoiceState("idle");
          await audioElement.play();
        } else if ("speechSynthesis" in window && payload.response) {
          setVoiceState("speaking");
          const utterance = new SpeechSynthesisUtterance(payload.response);
          utterance.onend = () => setVoiceState("idle");
          utterance.onerror = () => setVoiceState("idle");
          window.speechSynthesis.speak(utterance);
        } else {
          setVoiceState("idle");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Voice request failed");
        setVoiceState("idle");
      }
    };
    nextRecorder.start();
  }

  const displayedEvents = result?.reasoning_log?.length ? result.reasoning_log : liveEvents;

  return (
    <main className="shell">
      <header className="topbar sticky top-0 z-10">
        <div className="mx-auto flex max-w-content items-center justify-between px-5 py-4">
          <div>
            <p className="label">WORKPODD Support</p>
            <h1 className="display text-xl font-semibold">Refund workspace</h1>
          </div>
          <div className="flex items-center gap-3">
            <Link className="btn text-sm no-underline" href="/admin">
              Admin
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-content gap-5 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="panel flex min-h-[calc(100vh-8.5rem)] flex-col overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="label">Customer conversation</p>
                <h2 className="display text-lg font-semibold">Active refund request</h2>
              </div>
              {sessionId ? <span className="chip">{sessionId}</span> : <span className="chip">new session</span>}
            </div>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto bg-surface-subtle p-5">
            {messages.map((item, index) => (
                <div
                  key={`${item.role}-${index}`}
                  className={`flex ${item.role === "customer" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[76%] rounded-md border px-4 py-3 text-sm leading-6 ${
                      item.role === "customer"
                        ? "border-trust bg-trust text-white"
                        : "border-line bg-surface text-ink"
                    }`}
                  >
                    {item.content}
                  </div>
                </div>
              ))}
            {pending ? (
              <div className="panel max-w-xl p-4">
                <div className="flex items-center gap-3">
                  <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-review" />
                  <span className="text-sm font-semibold">Working through policy</span>
                  <span className="chip chip-review">{liveEvents.length} steps</span>
                </div>
                <p className="mt-2 text-xs text-muted">
                  {liveEvents.at(-1)?.summary ?? "Starting reasoning trace"}
                </p>
              </div>
            ) : null}
            {error ? <p className="text-sm text-deny">{error}</p> : null}
          </div>

          <div className="border-t border-line bg-surface p-4">
            <textarea
              className="field min-h-24 resize-none"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              maxLength={1000}
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <span className="tnum text-xs text-muted">{message.length}/1000</span>
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn" type="button" onClick={toggleRecording} disabled={pending}>
                  {voiceState === "recording" ? "Stop" : "Mic"}
                </button>
                <span className="chip">{voiceState}</span>
                <button className="btn btn-primary" type="button" onClick={submit} disabled={pending}>
                {pending ? "Working" : "Send"}
                </button>
              </div>
            </div>
          </div>
        </section>

        <aside className="space-y-5">
          <section className="panel p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="label">Case file</p>
                <h2 className="display text-lg font-semibold">Policy decision</h2>
              </div>
              <span className={verdictChip(result?.verdict)}>
                {result?.verdict ? statusLabel[result.verdict] ?? result.verdict : "Pending"}
              </span>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="panel-subtle p-3">
                <p className="label">Refund</p>
                <p className="tnum mt-1 text-xl font-semibold">{money(result?.refund_cents ?? 0)}</p>
              </div>
              <div className="panel-subtle p-3">
                <p className="label">Latest tool</p>
                <p className="tnum mt-1 truncate text-sm font-semibold">{latestTool}</p>
              </div>
            </div>
            <div className="mt-4">
              <p className="label">Clauses</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(result?.clauses_hit?.length ? result.clauses_hit : ["none"]).map((clause) => (
                  <span className="chip" key={clause}>
                    {clause}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section className="panel p-5">
            <div className="mb-4">
              <p className="label">Audit trail</p>
              <h2 className="display text-lg font-semibold">Reasoning timeline</h2>
            </div>
            <Timeline events={displayedEvents} />
          </section>
        </aside>
      </div>
    </main>
  );
}
