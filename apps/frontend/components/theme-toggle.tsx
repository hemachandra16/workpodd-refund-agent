"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

/** Compact light/dark/system toggle for the Ledger Calm shell. */
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
      className="btn tnum text-xs"
      aria-label="Cycle theme: light, dark, system"
      suppressHydrationWarning
    >
      {mounted ? (theme ?? "system") : "system"}
    </button>
  );
}
