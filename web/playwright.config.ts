/**
 * Playwright 冒烟（v0.2-4 retro 项：进 CI）。
 *
 * - 只测离线演示模式（mock 客户端，全链路脚本化事件流），不需要后端与真实 key；
 * - webServer 用 `vite preview` 起构建产物（先 npm run build），与部署形态一致；
 * - SPA 回退：preview 默认支持 history 路由刷新（vite 5+ appType spa）。
 */

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
