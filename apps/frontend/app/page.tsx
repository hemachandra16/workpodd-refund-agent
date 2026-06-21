import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";

export default function Home() {
  return (
    <main className="shell">
      <header className="topbar">
        <div className="mx-auto flex max-w-content items-center justify-between px-5 py-4">
          <div>
            <p className="label">WORPODD Support</p>
            <h1 className="display text-xl font-semibold">Refund operations</h1>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <section className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-content place-items-center px-5 py-10">
        <div className="grid w-full gap-5 md:grid-cols-2">
          <Link className="panel p-6 no-underline transition hover:border-trust" href="/chat?demo=1">
            <p className="label">Customer</p>
            <h2 className="display mt-2 text-2xl font-semibold">Refund workspace</h2>
            <p className="mt-3 text-sm leading-6 text-muted">Conversation, case file, policy decision, and Clause Rail timeline.</p>
          </Link>
          <Link className="panel p-6 no-underline transition hover:border-trust" href="/admin">
            <p className="label">Admin</p>
            <h2 className="display mt-2 text-2xl font-semibold">Reasoning operations</h2>
            <p className="mt-3 text-sm leading-6 text-muted">Auth-gated sessions, live event stream, retry markers, and audit context.</p>
          </Link>
        </div>
      </section>
    </main>
  );
}
