import type { Config } from "tailwindcss";

const c = (v: string) => `hsl(var(--${v}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        border: c("border"), input: c("input"), ring: c("ring"),
        background: c("background"), foreground: c("foreground"),
        primary: { DEFAULT: c("primary"), foreground: c("primary-foreground") },
        secondary: { DEFAULT: c("secondary"), foreground: c("secondary-foreground") },
        muted: { DEFAULT: c("muted"), foreground: c("muted-foreground") },
        accent: { DEFAULT: c("accent"), foreground: c("accent-foreground") },
        violet: { DEFAULT: c("violet"), soft: c("violet-soft") },
        info: c("info"),
        success: c("success"), warning: c("warning"), serious: c("serious"), critical: c("critical"),
        card: { DEFAULT: c("card"), foreground: c("card-foreground") },
        popover: { DEFAULT: c("popover"), foreground: c("popover-foreground") },
        sidebar: c("sidebar"),
      },
      borderRadius: { lg: "10px", md: "8px", sm: "6px" },
      fontSize: { "2xs": ["11px", "14px"] },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "none" } },
        pulse2: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".45" } },
      },
      animation: { "fade-in": "fade-in .18s ease-out", pulse2: "pulse2 1.6s ease-in-out infinite" },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
