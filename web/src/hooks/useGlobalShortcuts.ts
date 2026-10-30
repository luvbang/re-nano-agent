/**
 * 全局快捷键绑定（v0.2-4）：把 lib/shortcuts 的判定接到 document 上。
 *
 * 挂在 document 而不是某个容器：焦点可能在任何地方，甚至不在页面里。
 * 判定本身是纯函数（lib/shortcuts.ts），这里只负责取值、调用回调，
 * 以及命中后 preventDefault——"/" 不拦的话斜杠会同时被敲进输入框。
 */

import { useEffect, useRef, type MutableRefObject } from "react";
import { isEditableTarget, resolveShortcut } from "../lib/shortcuts";

export interface ShortcutHandlers {
  onFocusComposer: () => void;
  onOpenSearch: () => void;
}

/** 极小的 latest-ref：回调每次渲染都是新对象，直接进 deps 会让监听器反复解绑 */
function useLatest<T>(value: T): MutableRefObject<T> {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

/**
 * composer 用 data-composer 标记、由这里查询来聚焦：
 * Playground 是懒加载路由，从 Layout 直接把 ref 传下去会穿透 Suspense 边界，
 * 反而要在两层之间加一个只会被用一次的 context。全局唯一元素用查询更直白。
 */
export function focusComposer(root: Document = document): boolean {
  const el = root.querySelector<HTMLElement>("[data-composer]");
  if (!el) return false;
  el.focus();
  // 光标落到已有草稿末尾，继续写而不是覆盖位置。
  // 用 duck typing 而不是 instanceof：node 环境（单测）里没有这些 DOM 构造器
  const editable = el as HTMLTextAreaElement;
  if (typeof editable.value === "string" && typeof editable.setSelectionRange === "function") {
    editable.setSelectionRange(editable.value.length, editable.value.length);
  }
  return true;
}

/**
 * 跨页迟到聚焦：在非 Playground 页按 `/` 时先导航过去，composer 还没渲染，
 * 此刻查询必然落空。记一个待办，等页面挂载后自己来兑现。
 */
let pendingComposerFocus = false;

export function requestComposerFocus(): void {
  if (focusComposer()) {
    pendingComposerFocus = false;
    return;
  }
  pendingComposerFocus = true;
}

/**
 * 页面挂载时调用，返回是否兑现。
 *
 * 只在聚焦成功后才清待办：页面还没渲染出 composer（比如还停在绑定 Key 的
 * 引导态）时如果提前清掉，那次 `/` 就永远丢了。
 */
export function consumePendingComposerFocus(): boolean {
  if (!pendingComposerFocus) return false;
  if (!focusComposer()) return false;
  pendingComposerFocus = false;
  return true;
}

export function useGlobalShortcuts(handlers: ShortcutHandlers): void {
  const latest = useLatest(handlers);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const action = resolveShortcut({
        key: e.key,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        altKey: e.altKey,
        shiftKey: e.shiftKey,
        // keyCode 229 是老浏览器/部分 IME 的组合态信号，一并当作组合中
        isComposing: e.isComposing || e.keyCode === 229,
        editable: isEditableTarget(e.target),
      });
      if (action === null) return;

      e.preventDefault();
      if (action === "focus-composer") latest.current.onFocusComposer();
      else latest.current.onOpenSearch();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [latest]);
}
