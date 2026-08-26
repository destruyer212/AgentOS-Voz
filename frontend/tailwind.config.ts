import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          950: "#08090d",
          900: "#0d0f16",
          800: "#12151e",
          700: "#1a1e2b",
          600: "#252b3b",
          500: "#343c52",
        },
        brand: {
          400: "#8b8bf9",
          500: "#6d6df7",
          600: "#5652e8",
          700: "#4540c4",
        },
        accent: {
          teal: "#2dd4bf",
          amber: "#f6b03e",
          rose: "#f4667c",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.5)",
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
