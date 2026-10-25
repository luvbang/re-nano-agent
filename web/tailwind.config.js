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
        accent: {
          DEFAULT: "#34d399",
          dim: "#065f46",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
