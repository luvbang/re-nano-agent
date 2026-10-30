/**
 * 全局键盘快捷键的纯判定层（v0.2-4）。
 *
 * 为什么抽成纯函数：组合键过滤规则（输入法、修饰键、焦点位置）最容易回归，
 * 而 DOM 事件又最难测；这里只吃一个普通对象，测试不需要 jsdom。
 *
 * Esc 不在这里统一处理——每个浮层（TopicSearchDialog / MessageSearchDialog）
 * 自己挂 Esc：全局再挂一份会与浮层的局部监听抢执行顺序，关闭行为变得不可预测。
 */

export type ShortcutAction = "focus-composer" | "open-search";

/** 从 KeyboardEvent 摘出的最小字段集（不必构造真的 KeyboardEvent 就能测） */
export interface ShortcutKey {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  /** 输入法组合态（e.nativeEvent.isComposing 或 keyCode 229） */
  isComposing?: boolean;
  /** 焦点是否落在可编辑元素内 */
  editable?: boolean;
}

const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** 焦点在可编辑元素里：此时 `/` 应当照常输入，不能变成"聚焦输入框" */
export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as (HTMLElement & { tagName?: unknown }) | null;
  if (!el || typeof el.tagName !== "string") return false;
  if (EDITABLE_TAGS.has(el.tagName.toUpperCase())) return true;
  return el.isContentEditable === true;
}

/**
 * 把一次按键翻译成动作，命中不了返回 null。
 *
 * 约定：
 * - Ctrl/⌘+K 全局可开（焦点在输入框里也要能开，这是搜索类快捷键的惯例）；
 * - `/` 只在非输入区生效，且要求无 Shift——Shift+/ 在多数键盘布局上是 `?`，
 *   用户是想输入问号而不是聚焦；
 * - 输入法组合期间一律不触发：此时按键属于候选词选择，劫持会吞字；
 * - Ctrl+Alt 组合（Windows 的 AltGr）不算 Ctrl 快捷键。
 */
export function resolveShortcut(k: ShortcutKey): ShortcutAction | null {
  if (k.isComposing) return null;

  const primary = Boolean(k.ctrlKey || k.metaKey);
  const alt = Boolean(k.altKey);

  if (primary && !alt && (k.key === "k" || k.key === "K")) return "open-search";

  if (k.key === "/" && !primary && !alt && !k.shiftKey && !k.editable) return "focus-composer";

  return null;
}
