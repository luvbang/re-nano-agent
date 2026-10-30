/** lib/toast 状态机契约（v0.2-4）：堆叠上限、重复消息去重、按 id 关闭。 */

import { describe, expect, it } from "vitest";
import {
  MAX_TOASTS,
  initialToastState,
  toastReducer,
  type ToastItem,
} from "./toast";

const item = (id: number, tone: ToastItem["tone"] = "success", message = `m${id}`): ToastItem => ({
  id,
  tone,
  message,
});

describe("toastReducer：push", () => {
  it("追加到末尾（渲染顺序即出现顺序）", () => {
    const s1 = toastReducer(initialToastState, { type: "push", item: item(1) });
    const s2 = toastReducer(s1, { type: "push", item: item(2) });
    expect(s2.map((t) => t.id)).toEqual([1, 2]);
  });

  it("超过上限时挤掉最旧的，只留最近 MAX_TOASTS 条", () => {
    let s = initialToastState;
    for (let i = 1; i <= MAX_TOASTS + 2; i += 1) s = toastReducer(s, { type: "push", item: item(i) });
    expect(s).toHaveLength(MAX_TOASTS);
    expect(s.at(-1)?.id).toBe(MAX_TOASTS + 2);
    expect(s.some((t) => t.id === 1)).toBe(false);
  });

  it("同色同文案视为同一条，只保留最新 id（连点两次重命名不叠一墙）", () => {
    const s = toastReducer(
      toastReducer(initialToastState, { type: "push", item: item(1, "error", "重命名失败：x") }),
      { type: "push", item: item(2, "error", "重命名失败：x") },
    );
    expect(s).toHaveLength(1);
    expect(s[0]?.id).toBe(2);
  });

  it("文案相同但色不同是不同的提示", () => {
    const s = toastReducer(
      toastReducer(initialToastState, { type: "push", item: item(1, "success", "ok") }),
      { type: "push", item: item(2, "error", "ok") },
    );
    expect(s.map((t) => t.tone)).toEqual(["success", "error"]);
  });

  it("不改动传入的旧数组（reducer 必须纯）", () => {
    const before = [item(1)];
    const snapshot = [...before];
    toastReducer(before, { type: "push", item: item(2) });
    expect(before).toEqual(snapshot);
  });
});

describe("toastReducer：dismiss / clear", () => {
  it("按 id 移除", () => {
    const s = [item(1), item(2), item(3)];
    expect(toastReducer(s, { type: "dismiss", id: 2 }).map((t) => t.id)).toEqual([1, 3]);
  });

  it("id 不存在时返回同一个引用（省一次重渲染）", () => {
    const s = [item(1)];
    expect(toastReducer(s, { type: "dismiss", id: 99 })).toBe(s);
  });

  it("clear 清空；已经是空数组时保持引用不变", () => {
    expect(toastReducer([item(1)], { type: "clear" })).toEqual([]);
    expect(toastReducer(initialToastState, { type: "clear" })).toBe(initialToastState);
  });
});
