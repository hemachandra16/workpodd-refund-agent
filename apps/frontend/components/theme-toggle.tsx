"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

/**
 * Minimal light/dark/system toggle. Text labels only — no emoji, no icons —
 * consistent with the neobrutalist direction.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const cycle = () => {
    const order = ["light", "dark", "system"] as const;
    const idx = order.indexOf((theme as typeof order[number]) ?? "system");
    setTheme(order[(idx + 1) % order.length]);
  };

  return (
    <button
      type="button"
      onClick={cycle}
      className="btn tnum"
      aria-label="Cycle theme: light, dark, system"
      suppressHydrationWarning
    >
      {mounted ? (theme ?? "system") : "system"}
    </button>
  );
}
