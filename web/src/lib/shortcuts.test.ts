/**
 * lib/shortcuts 纯函数契约（v0.2-4）：组合键过滤是最容易回归的一块，
 * 这里把每条约定钉死——Windows 的 Ctrl 与 macOS 的 ⌘ 都要能开搜索，
 * 输入法组合和 Shift+/ 都不能被误当成快捷键。
 */

import { describe, expect, it } from "vitest";
import { isEditableTarget, resolveShortcut } from "./shortcuts";

describe("resolveShortcut：Ctrl/⌘+K 开搜索", () => {
  it("Ctrl+K / ⌘+K 都命中，大小写不敏感", () => {
    expect(resolveShortcut({ key: "k", ctrlKey: true })).toBe("open-search");
    expect(resolveShortcut({ key: "k", metaKey: true })).toBe("open-search");
    expect(resolveShortcut({ key: "K", ctrlKey: true })).toBe("open-search");
  });

  it("焦点在输入框里也照样命中（搜索类快捷键的惯例）", () => {
    expect(resolveShortcut({ key: "k", ctrlKey: true, editable: true })).toBe("open-search");
  });

  it("裸 k 不命中——否则打字就弹窗", () => {
    expect(resolveShortcut({ key: "k" })).toBeNull();
  });

  it("Ctrl+Alt+K 不命中：Windows 的 AltGr 会同时置起两个修饰键", () => {
    expect(resolveShortcut({ key: "k", ctrlKey: true, altKey: true })).toBeNull();
  });

  it("输入法组合期间不命中", () => {
    expect(resolveShortcut({ key: "k", ctrlKey: true, isComposing: true })).toBeNull();
  });
});

describe("resolveShortcut：/ 聚焦输入框", () => {
  it("非输入区裸斜杠命中", () => {
    expect(resolveShortcut({ key: "/" })).toBe("focus-composer");
  });

  it("输入框内不劫持——用户就是想打斜杠", () => {
    expect(resolveShortcut({ key: "/", editable: true })).toBeNull();
  });

  it("Shift+/ 不命中：多数布局上那是问号", () => {
    expect(resolveShortcut({ key: "/", shiftKey: true })).toBeNull();
  });

  it("带 Ctrl/⌘ 的斜杠不命中（留给浏览器的缩放等既有绑定）", () => {
    expect(resolveShortcut({ key: "/", ctrlKey: true })).toBeNull();
    expect(resolveShortcut({ key: "/", metaKey: true })).toBeNull();
  });

  it("输入法组合期间不命中", () => {
    expect(resolveShortcut({ key: "/", isComposing: true })).toBeNull();
  });
});

describe("resolveShortcut：其它按键一律放过", () => {
  it("Esc / Enter / 方向键不产生动作（Esc 由各浮层自己处理）", () => {
    for (const key of ["Escape", "Enter", "ArrowDown", "Tab", "?"]) {
      expect(resolveShortcut({ key })).toBeNull();
    }
  });
});

describe("isEditableTarget", () => {
  // node 环境没有 DOM，用最小假对象覆盖判定分支（函数只读了 tagName/isContentEditable）
  const fake = (tagName: string, isContentEditable = false) =>
    ({ tagName, isContentEditable }) as unknown as EventTarget;

  it("input / textarea / select 视为可编辑", () => {
    expect(isEditableTarget(fake("INPUT"))).toBe(true);
    expect(isEditableTarget(fake("TEXTAREA"))).toBe(true);
    expect(isEditableTarget(fake("SELECT"))).toBe(true);
    // 标签名大小写不敏感
    expect(isEditableTarget(fake("input"))).toBe(true);
  });

  it("contenteditable 元素视为可编辑", () => {
    expect(isEditableTarget(fake("DIV", true))).toBe(true);
  });

  it("普通元素与 null 都不算", () => {
    expect(isEditableTarget(fake("DIV"))).toBe(false);
    expect(isEditableTarget(fake("BUTTON"))).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });

  it("没有 tagName 的对象不炸（事件目标可能是 window / document）", () => {
    expect(isEditableTarget({} as unknown as EventTarget)).toBe(false);
  });
});
