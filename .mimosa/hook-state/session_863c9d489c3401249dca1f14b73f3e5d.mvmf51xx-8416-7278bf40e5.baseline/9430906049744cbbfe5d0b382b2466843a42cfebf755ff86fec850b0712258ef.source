import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dev: Vite :5173，/v1、/healthz、/readyz 代理到本地后端（同源行为与生产一致）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
      "/readyz": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 280,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
