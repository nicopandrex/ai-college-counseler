import type { Config } from "tailwindcss";

/** School-planner sketch: cream paper, pen ink, highlighters. */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FBF7EC",
        desk: "#EFE6D2",
        ink: "#27304A", // ballpoint blue-black
        pencil: "#6E6A75",
        ruled: "#CFDDEB",
        margin: "#EE9A95",
        hl: {
          yellow: "#FFF07A",
          pink: "#FFC2DC",
          green: "#C8EDB4",
          blue: "#B8DEF5",
          orange: "#FFD2A1",
          purple: "#DCCBF5",
          mint: "#BDEBDD",
        },
        pen: { red: "#D9453B", blue: "#2C5BB8" },
      },
      fontFamily: {
        sans: ["var(--font-hand)", "Comic Sans MS", "cursive"],
        marker: ["var(--font-marker)", "var(--font-hand)", "cursive"],
      },
      keyframes: {
        wiggle: { "0%, 100%": { transform: "rotate(-6deg)" }, "50%": { transform: "rotate(6deg)" } },
      },
      animation: { wiggle: "wiggle 0.6s ease-in-out infinite" },
    },
  },
  plugins: [],
};
export default config;
