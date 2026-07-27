import type { Config } from "tailwindcss";

// Every colour is a CSS variable (see globals.css) so all utilities are
// theme-aware without a `dark:` variant. Breakpoints start at 360px because
// low-end Android is the real floor for this audience.
const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    screens: { xs: "360px", sm: "480px", md: "768px", lg: "1024px", xl: "1280px", "2xl": "1536px" },
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-subtle": "var(--bg-subtle)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",
        "surface-hover": "var(--surface-hover)",
        border: "var(--border)",
        "border-mid": "var(--border-mid)",
        "border-strong": "var(--border-strong)",
        fg: "var(--fg)",
        "fg-muted": "var(--fg-muted)",
        "fg-faint": "var(--fg-faint)",
        accent: "var(--accent)",
        "accent-strong": "var(--accent-strong)",
        "accent-fg": "var(--accent-fg)",
        "accent-soft": "var(--accent-soft)",
        "accent-line": "var(--accent-line)",
        danger: "var(--danger)",
        "danger-soft": "var(--danger-soft)",
        warn: "var(--warn)",
        "warn-soft": "var(--warn-soft)",
        ok: "var(--ok)",
        "ok-soft": "var(--ok-soft)",
      },
      fontFamily: {
        display: "var(--font-display)",
        read: "var(--font-read)",
        ui: "var(--font-ui)",
        mono: "var(--font-mono)",
      },
      // Editorial hybrid: sharp for content, soft for chrome.
      borderRadius: {
        none: "var(--r-none)",
        xs: "var(--r-xs)",
        sm: "var(--r-sm)",
        DEFAULT: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
        full: "var(--r-full)",
      },
      borderColor: { DEFAULT: "var(--border)" },
      boxShadow: {
        sm: "var(--shadow-sm)",
        soft: "var(--shadow)",
        lg: "var(--shadow-lg)",
        none: "none",
      },
      transitionTimingFunction: {
        soft: "var(--ease-out-soft)",
        expo: "var(--ease-out-expo)",
        organic: "var(--ease-organic)",
        "in-out-soft": "var(--ease-in-out-soft)",
      },
      transitionDuration: {
        instant: "90ms",
        fast: "150ms",
        DEFAULT: "260ms",
        slow: "420ms",
        panel: "520ms",
      },
      maxWidth: { chat: "46rem", content: "52rem", prose: "38rem" },
      fontSize: {
        // Dramatic editorial range (design.md type scale).
        "2xs": ["0.6875rem", { lineHeight: "1.4" }],
        "7xl": ["6rem", { lineHeight: "1" }],
        "8xl": ["8rem", { lineHeight: "0.95" }],
        "9xl": ["10rem", { lineHeight: "0.92" }],
      },
      letterSpacing: { editorial: "-0.025em", widest: "0.14em" },
      zIndex: { panel: "40", overlay: "50", toast: "60" },
    },
  },
  plugins: [],
};

export default config;
