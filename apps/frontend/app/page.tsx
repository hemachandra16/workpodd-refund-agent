import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Landing shell. Real chat surface lands in Phase 6; this confirms the design
 * system + theme system render correctly end-to-end.
 */
export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <header className="border-b border-border">
        <div className="max-w-content mx-auto px-6 py-4 flex items-center justify-between">
          <span className="tnum text-sm tracking-widest uppercase">WORPODD · Support</span>
          <ThemeToggle />
        </div>
      </header>

      <section className="flex-1 flex items-center justify-center px-6">
        <div className="panel max-w-md w-full p-8">
          <h1 className="text-3xl font-bold tracking-tight">Refund agent</h1>
          <p className="mt-3 text-muted">
            An automated support agent that resolves or denies e-commerce refunds
            against a strict policy. Voice-enabled, fully logged.
          </p>
          <div className="mt-6 flex gap-3">
            <Link href="/chat" className="btn btn-primary no-underline">Open chat</Link>
            <Link href="/admin" className="btn no-underline">Admin</Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="max-w-content mx-auto px-6 py-3 tnum text-xs uppercase tracking-widest text-muted">
          v0.1.0 · build scaffold
        </div>
      </footer>
    </main>
  );
}
