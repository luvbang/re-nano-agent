/**
 * 轻量 toast（v0.2-4）：Context + 一组固定位浮层，不引第三方依赖。
 *
 * 设计取舍：
 * - 用模块级 reducer 做状态（规则见 lib/toast.ts），本组件只管计时与渲染；
 * - 自动消失用 setTimeout 而不是 CSS 动画的 animationend：浮层可能在
 *   后台标签页里被浏览器暂停动画，计时器语义更确定；
 * - aria-live="polite"：读屏器排队播报，不打断用户当前操作。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import {
  TOAST_DURATION_MS,
  initialToastState,
  toastReducer,
  type ToastItem,
  type ToastTone,
} from "../lib/toast";
import { copy } from "../lib/copy";
import { AlertIcon, CheckIcon, CloseIcon } from "./icons";

export interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/** 视觉沿用 data-terminal 的 pill 配色（与 ui.tsx 的 tone 一一对应） */
const TONE_CLASSES: Record<ToastTone, string> = {
  success: "border-pos/30 bg-pill-pos text-pos",
  error: "border-neg/30 bg-pill-neg text-neg",
};

function ToastRow({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  return (
    <div
      className={`pointer-events-auto flex w-72 animate-fade-up items-start gap-2 rounded-lg border px-3 py-2 shadow-pop ${TONE_CLASSES[item.tone]}`}
    >
      <span className="mt-0.5 flex-none">
        {item.tone === "success" ? <CheckIcon /> : <AlertIcon className="h-3.5 w-3.5" />}
      </span>
      <p className="min-w-0 flex-1 break-words text-sm leading-snug">{item.message}</p>
      <button
        type="button"
        title={copy.toast.dismiss}
        aria-label={copy.toast.dismiss}
        onClick={() => onDismiss(item.id)}
        className="flex h-5 w-5 flex-none items-center justify-center rounded text-mut transition-colors hover:text-ink"
      >
        <CloseIcon />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, dispatch] = useReducer(toastReducer, initialToastState);
  const seq = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    const t = timers.current.get(id);
    if (t !== undefined) {
      clearTimeout(t);
      timers.current.delete(id);
    }
    dispatch({ type: "dismiss", id });
  }, []);

  const push = useCallback(
    (tone: ToastTone, message: string) => {
      seq.current += 1;
      const id = seq.current;
      dispatch({ type: "push", item: { id, tone, message } });
      timers.current.set(
        id,
        setTimeout(() => {
          timers.current.delete(id);
          dispatch({ type: "dismiss", id });
        }, TOAST_DURATION_MS),
      );
    },
    [],
  );

  // 卸载时清空挂起的计时器，避免对已卸载的树 dispatch
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const t of pending.values()) clearTimeout(t);
      pending.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (message: string) => push("success", message),
      error: (message: string) => push("error", message),
      dismiss,
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* 固定在右下角、不拦截点击（只有卡片本身可点） */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2"
      >
        {toasts.map((t) => (
          <ToastRow key={t.id} item={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
