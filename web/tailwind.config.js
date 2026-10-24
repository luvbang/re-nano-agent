/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "oklch(0.16 0.01 260)",
        panel: "oklch(0.21 0.01 260)",
        line: "oklch(0.30 0.01 260)",
        ink: "oklch(0.95 0.005 260)",
        dim: "oklch(0.65 0.01 260)",
        accent: "oklch(0.72 0.15 250)",
      },
    },
  },
  plugins: [],
};
