/**
 * Run 事件投影（纯函数）：SSE 事件流 → 页面渲染模型。
 *
 * 约束（web-architecture §4）：
 * - 投影是 (state, event) => state，输入输出可序列化，组件只渲染不计算。
 * - message.completed 的全文**覆盖**本地累积的 delta（契约：续传不补增量，
 *   completed 才是真相）。
 * - 工具轮之后可能开启新的 assistant 段（模型 → 工具 → 模型 → 回答）。
 */

import type { RunError, RunStreamEvent, SessionMessage, Usage } from "../api/types";

export interface ToolCallView {
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  duration_ms: number | null;
}

export type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; streaming: boolean; tools: ToolCallView[] };

export type RunPhase = "idle" | "streaming" | "completed" | "failed" | "cancelled";

export interface RunProjection {
  phase: RunPhase;
  items: ChatItem[];
  usage: Usage | null;
  error: RunError | null;
  lastSeq: number;
}

export function initialProjection(): RunProjection {
  return { phase: "idle", items: [], usage: null, error: null, lastSeq: 0 };
}

function openAssistant(items: ChatItem[]): ChatItem[] {
  const last = items[items.length - 1];
  if (last && last.kind === "assistant") {
    if (!last.streaming) return [...items, newAssistantSegment()];
    // 当前段的最后一个工具已完成 → 工具轮结束，后续 delta 属于新的模型回答段
    const lastTool = last.tools[last.tools.length - 1];
    if (lastTool && lastTool.status !== "running") return [...items, newAssistantSegment()];
    return items;
  }
  return [...items, newAssistantSegment()];
}

function newAssistantSegment(): ChatItem {
  return { kind: "assistant", text: "", streaming: true, tools: [] };
}

function closeAssistant(items: ChatItem[]): ChatItem[] {
  const last = items[items.length - 1];
  if (last && last.kind === "assistant" && last.streaming) {
    return [...items.slice(0, -1), { ...last, streaming: false }];
  }
  return items;
}

function updateLastAssistant(
  items: ChatItem[],
  update: (item: Extract<ChatItem, { kind: "assistant" }>) => ChatItem,
): ChatItem[] {
  const last = items[items.length - 1];
  if (!last || last.kind !== "assistant") return items;
  return [...items.slice(0, -1), update(last)];
}

export function applyEvent(state: RunProjection, ev: RunStreamEvent): RunProjection {
  const next: RunProjection = { ...state, lastSeq: ev.seq };
  switch (ev.type) {
    case "run.started":
      return { ...next, phase: "streaming" };
    case "message.delta":
      return {
        ...next,
        phase: "streaming",
        items: updateLastAssistant(openAssistant(next.items), (a) => ({
          ...a,
          text: a.text + ev.delta,
        })),
      };
    case "reasoning.delta":
      return next; // v0.1 控制台不渲染推理流，仅保序推进 seq
    case "tool.started":
      return {
        ...next,
        phase: "streaming",
        items: updateLastAssistant(openAssistant(next.items), (a) => ({
          ...a,
          tools: [
            ...a.tools,
            {
              tool_call_id: ev.tool_call_id,
              name: ev.name,
              args: ev.args,
              status: "running",
              duration_ms: null,
            },
          ],
        })),
      };
    case "tool.completed":
      return {
        ...next,
        items: updateLastAssistant(next.items, (a) => ({
          ...a,
          tools: a.tools.map((t) =>
            t.tool_call_id === ev.tool_call_id
              ? { ...t, status: ev.status, duration_ms: ev.duration_ms }
              : t,
          ),
        })),
      };
    case "message.completed":
      // 全文覆盖 delta 累积（契约语义）；同段的工具卡保留
      return {
        ...next,
        items: updateLastAssistant(openAssistant(next.items), (a) => ({
          kind: "assistant",
          text: ev.content,
          streaming: false,
          tools: a.tools,
        })),
      };
    case "run.completed":
      return {
        ...next,
        phase: "completed",
        usage: ev.usage,
        items: closeAssistant(next.items),
      };
    case "run.failed":
      return { ...next, phase: "failed", error: ev.error, items: closeAssistant(next.items) };
    case "run.cancelled":
      return { ...next, phase: "cancelled", items: closeAssistant(next.items) };
  }
}

/** 把 GET messages 的历史重建为渲染模型（续聊场景）。 */
export function historyToItems(messages: SessionMessage[]): ChatItem[] {
  const items: ChatItem[] = [];
  const toolNameById = new Map<string, string>();
  for (const m of messages) {
    if (m.role === "user" && m.content !== null) {
      items.push({ kind: "user", text: m.content });
    } else if (m.role === "assistant") {
      const tools: ToolCallView[] = (m.tool_calls ?? []).map((c) => {
        toolNameById.set(c.id, c.function.name);
        return {
          tool_call_id: c.id,
          name: c.function.name,
          args: safeParse(c.function.arguments),
          status: "ok",
          duration_ms: null,
        };
      });
      items.push({
        kind: "assistant",
        text: m.content ?? "",
        streaming: false,
        tools,
      });
    } else if (m.role === "tool" && m.tool_call_id) {
      // 工具结果消息：并入前一条 assistant 的工具卡（历史里只有 ok 态）
      const last = items[items.length - 1];
      if (last && last.kind === "assistant") {
        const name = toolNameById.get(m.tool_call_id) ?? "tool";
        const exists = last.tools.some((t) => t.tool_call_id === m.tool_call_id);
        if (!exists) {
          items[items.length - 1] = {
            ...last,
            tools: [
              ...last.tools,
              {
                tool_call_id: m.tool_call_id,
                name,
                args: {},
                status: "ok",
                duration_ms: null,
              },
            ],
          };
        }
      }
    }
    // system / summary 不进入对话视图
  }
  return items;
}

function safeParse(json: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(json) as unknown;
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}
