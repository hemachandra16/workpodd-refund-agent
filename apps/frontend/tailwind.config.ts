import type { Config } from "tailwindcss";

/**
 * WORPODD design system.
 * Minimalism + neobrutalist structure:
 *   - hard 1px borders, near-zero radius, bold display type
 *   - JetBrains Mono for numerics/IDs/logs
 *   - single forest-green accent, no gradients, no shadows, no emoji
 *   - high-contrast light + dark via CSS variables + next-themes
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Semantic tokens bound to CSS variables (see globals.css).
        bg: "var(--bg)",
        surface: "var(--surface)",
        border: "var(--border)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        deny: "var(--deny)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        // Intentionally tiny — neobrutalist.
        none: "0px",
        xs: "2px",
        sm: "3px",
      },
      boxShadow: {
        // No soft shadows. One hard offset border-shadow for emphasis only.
        edge: "2px 2px 0 0 var(--border)",
      },
      maxWidth: {
        content: "72rem",
      },
    },
  },
  plugins: [],
};

export default config;
