import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发模式与生产同源行为一致：API 与 SSE 都打到后端
      "/v1": { target: "http://127.0.0.1:8000", changeOrigin: false },
      "/healthz": { target: "http://127.0.0.1:8000", changeOrigin: false },
      "/readyz": { target: "http://127.0.0.1:8000", changeOrigin: false },
      "/metrics": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { sourcemap: false },
});
