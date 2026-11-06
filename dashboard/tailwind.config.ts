import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
      keyframes: {
        necropulse: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(239,68,68,0.7)", opacity: "1" },
          "50%": { boxShadow: "0 0 24px 6px rgba(239,68,68,0.5)", opacity: "0.65" },
        },
      },
      animation: { necropulse: "necropulse 1.1s ease-in-out infinite" },
    },
  },
  plugins: [],
};
export default config;
