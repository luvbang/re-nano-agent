import { describe, expect, it } from "vitest";

import type { StreamEvent } from "../api/types";
import { applyEvent, fromHistory, initialState } from "./runProjection";

function event(type: string, data: Record<string, unknown>, seq = 1): StreamEvent {
  return { seq, type, data };
}

describe("runProjection", () => {
  it("增量累积，completed 全文覆盖", () => {
    let state = applyEvent(initialState, event("run.started", { run_id: "r" }));
    state = applyEvent(state, event("message.delta", { delta: "你" }, 2));
    state = applyEvent(state, event("message.delta", { delta: "好" }, 3));
    state = applyEvent(state, event("message.completed", { content: "你好！", usage: { input_tokens: 5, output_tokens: 2 } }, 4));
    state = applyEvent(state, event("run.completed", { usage: { input_tokens: 5, output_tokens: 2 } }, 5));

    expect(state.items[state.items.length - 1]).toEqual({ kind: "assistant", text: "你好！" });
    expect(state.streaming).toBe(false);
    expect(state.usage).toEqual({ input: 5, output: 2 });
  });

  it("工具卡生命周期：started → completed(ok) 带时长", () => {
    let state = applyEvent(initialState, event("run.started", {}));
    state = applyEvent(
      state,
      event("tool.started", { tool_call_id: "t1", name: "get_time", args: {} }, 2),
    );
    state = applyEvent(
      state,
      event("tool.completed", { tool_call_id: "t1", name: "get_time", status: "ok", duration_ms: 12 }, 3),
    );
    const tool = state.items.find((item) => item.kind === "tool");
    expect(tool).toMatchObject({ id: "t1", name: "get_time", status: "ok", durationMs: 12 });
  });

  it("run.failed 记录错误并停止流式", () => {
    let state = applyEvent(initialState, event("run.started", {}));
    state = applyEvent(
      state,
      event("run.failed", { error: { code: "rate_limited", message: "慢点" } }, 2),
    );
    expect(state.streaming).toBe(false);
    expect(state.error).toEqual({ code: "rate_limited", message: "慢点" });
  });

  it("未知事件类型不炸", () => {
    const state = applyEvent(initialState, event("future.event", { x: 1 }));
    expect(state).toBe(initialState);
  });

  it("历史消息重建只保留气泡", () => {
    const items = fromHistory([
      { role: "user", content: "问" },
      { role: "assistant", content: null, tool_calls: undefined } as never,
      { role: "tool", content: "结果" },
      { role: "assistant", content: "答" },
    ]);
    expect(items).toEqual([
      { kind: "user", text: "问" },
      { kind: "assistant", text: "" },
      { kind: "assistant", text: "答" },
    ]);
  });
});
