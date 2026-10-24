/** 事件投影（纯函数）：SSE 事件流 → ChatView 模型。契约规定以 message.completed 为准。 */

import type { StreamEvent } from "../api/types";

export interface ToolItem {
  kind: "tool";
  id: string;
  name: string;
  args: string;
  status: "running" | "ok" | "error";
  durationMs: number | null;
}

export interface BubbleItem {
  kind: "user" | "assistant";
  text: string;
}

export type ChatItem = BubbleItem | ToolItem;

export interface RunState {
  items: ChatItem[];
  streaming: boolean;
  usage: { input: number; output: number } | null;
  error: { code: string; message: string } | null;
}

export const initialState: RunState = { items: [], streaming: false, usage: null, error: null };

function ensureTrailingAssistant(items: ChatItem[]): ChatItem[] {
  const last = items[items.length - 1];
  if (last && last.kind === "assistant") return items;
  return [...items, { kind: "assistant", text: "" }];
}

export function applyEvent(state: RunState, event: StreamEvent): RunState {
  switch (event.type) {
    case "run.started":
      return { ...state, items: [...state.items, { kind: "user", text: "" }], streaming: true };
    case "message.delta": {
      const delta = String(event.data.delta ?? "");
      const items = ensureTrailingAssistant(state.items);
      const last = items[items.length - 1] as BubbleItem;
      const patched = items.slice(0, -1).concat({ kind: "assistant", text: last.text + delta });
      return { ...state, items: patched, streaming: true };
    }
    case "message.completed": {
      // 契约真相：全文覆盖本地累积的增量
      const content = String(event.data.content ?? "");
      const items = ensureTrailingAssistant(state.items);
      const patched = items.slice(0, -1).concat({ kind: "assistant", text: content });
      const usage = event.data.usage as { input_tokens?: number; output_tokens?: number } | undefined;
      return {
        ...state,
        items: patched,
        usage: usage
          ? { input: usage.input_tokens ?? 0, output: usage.output_tokens ?? 0 }
          : state.usage,
      };
    }
    case "tool.started":
      return {
        ...state,
        items: [
          ...state.items,
          {
            kind: "tool",
            id: String(event.data.tool_call_id ?? ""),
            name: String(event.data.name ?? ""),
            args: JSON.stringify(event.data.args ?? {}),
            status: "running",
            durationMs: null,
          },
        ],
        streaming: true,
      };
    case "tool.completed":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "tool" && item.id === String(event.data.tool_call_id ?? "")
            ? {
                ...item,
                status: event.data.status === "ok" ? "ok" : "error",
                durationMs: Number(event.data.duration_ms ?? 0),
              }
            : item,
        ),
      };
    case "run.completed": {
      const usage = event.data.usage as { input_tokens?: number; output_tokens?: number } | undefined;
      return {
        ...state,
        streaming: false,
        usage: usage ? { input: usage.input_tokens ?? 0, output: usage.output_tokens ?? 0 } : state.usage,
      };
    }
    case "run.failed": {
      const error = event.data.error as { code?: string; message?: string } | undefined;
      return {
        ...state,
        streaming: false,
        error: { code: error?.code ?? "unknown", message: error?.message ?? "run 失败" },
      };
    }
    case "run.cancelled":
      return { ...state, streaming: false };
    default:
      return state;
  }
}

/** 把已落库的历史消息转成气泡（进入会话时重建视图；工具消息折叠为只读卡）。 */
export function fromHistory(messages: { role: string; content: string | null }[]): ChatItem[] {
  return messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      kind: message.role === "user" ? ("user" as const) : ("assistant" as const),
      text: message.content ?? "",
    }));
}
