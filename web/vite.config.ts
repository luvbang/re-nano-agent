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
    // 仍用 node 环境（不引 jsdom）：本项目把可测逻辑抽成纯函数/纯类，
    // 组件测试只做渲染树的静态断言。.tsx 一并纳入，组件测试才不用为了
    // 后缀把 JSX 改写成 createElement。
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
