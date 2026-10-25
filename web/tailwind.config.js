/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 深色运维控制台基调（web-architecture.md §2：单人可维护的甜点位）
        surface: {
          DEFAULT: "#0f1115",
          raised: "#171a21",
          border: "#262b36",
        },
        // 品牌色：🍁 枫叶琥珀（原 emerald 系换成 maple 系）
        accent: {
          DEFAULT: "#f59e0b",
          dim: "#78350f",
          soft: "#fbbf24",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.25), 0 4px 16px -8px rgb(0 0 0 / 0.35)",
        pop: "0 8px 32px -8px rgb(0 0 0 / 0.55)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
