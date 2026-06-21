import type { Config } from "tailwindcss";

/** Ledger Calm design system tokens mapped from app/globals.css. */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        mist: "var(--mist)",
        surface: "var(--surface)",
        "surface-subtle": "var(--surface-subtle)",
        line: "var(--line)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        trust: "var(--trust)",
        approval: "var(--approval)",
        review: "var(--review)",
        deny: "var(--deny)",
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xs: "4px",
        sm: "6px",
        md: "8px",
      },
      boxShadow: {
        calm: "0 8px 24px rgba(23, 32, 28, 0.08)",
      },
      maxWidth: {
        content: "78rem",
      },
    },
  },
  plugins: [],
};

export default config;
