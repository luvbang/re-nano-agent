/**
 * Toast 的纯状态层（v0.2-4）：不引第三方库，只维护一个 ToastItem[]。
 *
 * 为什么是 reducer 而不是 provider 里边算边 setState：堆叠上限、去重、
 * 按 id 关闭这三条规则是行为契约，抽出来就能在 node 环境里直接测，
 * provider 只负责计时器和渲染。
 */

export type ToastTone = "success" | "error";

export interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

export type ToastAction =
  | { type: "push"; item: ToastItem }
  | { type: "dismiss"; id: number }
  | { type: "clear" };

/** 同时最多显示几条：再多会盖住右下角的操作区，旧的整体挤掉 */
export const MAX_TOASTS = 4;

/** 自动消失时长（毫秒）；错误也走同一档，靠手动关闭兜底长文案 */
export const TOAST_DURATION_MS = 3000;

export const initialToastState: ToastItem[] = [];

export function toastReducer(state: ToastItem[], action: ToastAction): ToastItem[] {
  switch (action.type) {
    case "push": {
      // 同色同文案视为同一条：重复失败（比如连点两次重命名）只刷新计时，
      // 不叠一墙一样的提示
      const rest = state.filter(
        (t) => !(t.tone === action.item.tone && t.message === action.item.message),
      );
      const next = [...rest, action.item];
      return next.length > MAX_TOASTS ? next.slice(next.length - MAX_TOASTS) : next;
    }
    case "dismiss": {
      const next = state.filter((t) => t.id !== action.id);
      // 未命中返回原引用：让 React 少一次重渲染
      return next.length === state.length ? state : next;
    }
    case "clear":
      return state.length === 0 ? state : [];
  }
}
