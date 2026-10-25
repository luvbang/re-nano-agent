/**
 * 控制台冒烟（离线演示模式）：
 * 1. 登录页 → 演示模式按钮进入 Playground；
 * 2. Playground 发消息 → 工具卡（含结果预览）→ 回答完成；
 * 3. 各管理页在演示数据下可渲染（会话 / Keys / 用量明细+导出 / 状态）。
 */

import { expect, test } from "@playwright/test";

/** 直进演示模式：页面加载前种下 sessionStorage（与 useAdminKey 的存储键一致）。 */
async function gotoDemo(page: import("@playwright/test").Page, path = "/playground") {
  await page.addInitScript(() => {
    sessionStorage.setItem("agentd.clientMode", "demo");
    sessionStorage.setItem("agentd.adminKey", "agd_demo");
  });
  await page.goto(path);
}

test("登录页可进离线演示模式", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("登录 agentd 控制台")).toBeVisible();
  await page.getByRole("button", { name: "进入离线演示模式" }).click();
  await expect(page).toHaveURL(/playground/);
  await expect(page.getByText("当前为离线演示模式")).toBeVisible();
});

test("Playground 全链路：Key 门控 → 绑定项目 Key → 发送 → 工具卡（结果预览）→ 完成", async ({ page }) => {
  await gotoDemo(page);

  // v0.2-4 门控：未绑定项目 Key 时对话页显示引导（而非 composer）
  await expect(page.getByText("对话功能需要项目 Key")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "去 Keys 页绑定 →" }).click();
  await expect(page).toHaveURL(/keys/);

  // 建一个项目 Key 并绑定到 Playground（明文只显示一次的对话框）
  await page.getByRole("combobox").selectOption({ label: "默认项目" });
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  await expect(page.getByText("Key 已创建")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "在 Playground 使用" }).click();
  await expect(page.getByText("已绑定到 Playground").first()).toBeVisible();

  // 回 Playground：composer 可用，发消息
  await page.goto("/playground");
  const box = page.getByPlaceholder("输入消息，回车发送（Shift+Enter 换行）");
  await expect(box).toBeEnabled({ timeout: 10_000 });
  await box.fill("现在几点了");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  // 工具卡出现并可展开看结果预览（v0.2-4）
  const toolCard = page.getByRole("button", { name: /get_time/ });
  await expect(toolCard).toBeVisible({ timeout: 15_000 });
  await toolCard.click();
  await expect(page.getByText("结果")).toBeVisible();
  await expect(page.getByText(/utc=/)).toBeVisible();

  // run 完成：终稿包含演示文案（mock 的 message.completed 全文）
  await expect(page.getByText(/查询完成/)).toBeVisible({ timeout: 15_000 });
});

test("会话 / Keys / 用量 / 状态 页演示数据可渲染", async ({ page }) => {
  await gotoDemo(page, "/sessions");
  await expect(page.getByText("会话")).toBeVisible();
  await expect(page.getByText(/部署排障|文档问答/).first()).toBeVisible();

  await page.goto("/keys");
  await expect(page.getByRole("heading", { name: "API Keys" })).toBeVisible();
  await expect(page.getByText("playground 集成").first()).toBeVisible();

  await page.goto("/usage");
  await expect(page.getByText("总运行数")).toBeVisible({ timeout: 10_000 });
  // v0.2-4：明细表 + 导出按钮
  await expect(page.getByText("明细")).toBeVisible();
  await expect(page.getByRole("button", { name: /导出 CSV/ })).toBeEnabled();

  await page.goto("/status");
  await expect(page.getByText("系统状态")).toBeVisible();
  await expect(page.getByText(/运行时长|运行概况/).first()).toBeVisible();
});
