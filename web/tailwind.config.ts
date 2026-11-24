import type { Config } from "tailwindcss";

/** Bauhaus palette: three primaries on warm paper, black for structure. */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F3EFE6",
        ink: "#141414",
        rule: "#D8D1C2",
        red: { DEFAULT: "#D7322A" },
        blue: { DEFAULT: "#1D4FA0" },
        yellow: { DEFAULT: "#F2B705" },
      },
      fontFamily: {
        sans: ["var(--font-jost)", "Futura", "Century Gothic", "Avenir Next", "sans-serif"],
      },
      keyframes: {
        pulsebar: { "0%, 100%": { opacity: "0.25" }, "50%": { opacity: "1" } },
      },
      animation: { pulsebar: "pulsebar 1s ease-in-out infinite" },
    },
  },
  plugins: [],
};
export default config;
