/** 投影测试：契约事件的典型序列 → 终态断言（fixture 与后端 respx fixture 同源同语言）。 */

import { describe, expect, it } from "vitest";
import type { RunStreamEvent, SessionMessage } from "../api/types";
import {
  applyEvent,
  historyToItems,
  initialProjection,
} from "./run-projection";

function run(events: RunStreamEvent[]) {
  let state = initialProjection();
  for (const ev of events) state = applyEvent(state, ev);
  return state;
}

const START: RunStreamEvent = {
  type: "run.started",
  seq: 1,
  run_id: "r_1",
  session_id: "s_1",
};

describe("run-projection 纯文本流", () => {
  it("delta 逐字累积，completed 全文覆盖", () => {
    const state = run([
      START,
      { type: "message.delta", seq: 2, delta: "你" },
      { type: "message.delta", seq: 3, delta: "好" },
      {
        type: "message.completed",
        seq: 4,
        content: "你好（全文）",
        usage: { input_tokens: 5, output_tokens: 3 },
      },
      { type: "run.completed", seq: 5, usage: { input_tokens: 5, output_tokens: 3 } },
    ]);
    expect(state.phase).toBe("completed");
    expect(state.items).toEqual([
      { kind: "assistant", text: "你好（全文）", streaming: false, tools: [] },
    ]);
    expect(state.usage).toEqual({ input_tokens: 5, output_tokens: 3 });
    expect(state.lastSeq).toBe(5);
  });

  it("completed 覆盖丢失的 delta（断流重连语义：completed 才是真相）", () => {
    const state = run([
      START,
      { type: "message.delta", seq: 2, delta: "只收到前半" },
      // 断流：seq 3-5 丢失，直接收到 completed
      {
        type: "message.completed",
        seq: 6,
        content: "完整回答全文",
        usage: { input_tokens: 9, output_tokens: 9 },
      },
      { type: "run.completed", seq: 7, usage: { input_tokens: 9, output_tokens: 9 } },
    ]);
    const assistant = state.items[0];
    expect(assistant?.kind === "assistant" && assistant.text).toBe("完整回答全文");
  });
});

describe("run-projection 工具回路", () => {
  it("模型 → 工具 → 模型 → 回答：两段 assistant，工具卡状态流转", () => {
    const state = run([
      START,
      { type: "message.delta", seq: 2, delta: "我查一下时间" },
      { type: "tool.started", seq: 3, tool_call_id: "t_1", name: "get_time", args: {} },
      { type: "tool.completed", seq: 4, tool_call_id: "t_1", name: "get_time", status: "ok", duration_ms: 12 },
      { type: "message.delta", seq: 5, delta: "现在是 10 点" },
      {
        type: "message.completed",
        seq: 6,
        content: "现在是 10 点",
        usage: { input_tokens: 12, output_tokens: 8 },
      },
      { type: "run.completed", seq: 7, usage: { input_tokens: 12, output_tokens: 8 } },
    ]);
    expect(state.phase).toBe("completed");
    // 第一段（含工具卡）+ 第二段（最终回答）
    expect(state.items).toHaveLength(2);
    const first = state.items[0];
    if (first?.kind !== "assistant") throw new Error("unreachable");
    expect(first.text).toBe("我查一下时间");
    expect(first.tools).toEqual([
      { tool_call_id: "t_1", name: "get_time", args: {}, status: "ok", duration_ms: 12 },
    ]);
    const second = state.items[1];
    expect(second?.kind === "assistant" && second.text).toBe("现在是 10 点");
  });

  it("工具失败不中断流，状态标 error", () => {
    const state = run([
      START,
      { type: "tool.started", seq: 2, tool_call_id: "t_9", name: "read_file", args: { path: "../x" } },
      { type: "tool.completed", seq: 3, tool_call_id: "t_9", name: "read_file", status: "error", duration_ms: 3 },
      {
        type: "message.completed",
        seq: 4,
        content: "读取被安全边界拒绝了",
        usage: { input_tokens: 8, output_tokens: 6 },
      },
      { type: "run.completed", seq: 5, usage: { input_tokens: 8, output_tokens: 6 } },
    ]);
    const first = state.items[0];
    if (first?.kind !== "assistant") throw new Error("unreachable");
    expect(first.tools[0]?.status).toBe("error");
  });

  it("run.failed 收敛为失败态并关闭流式光标", () => {
    const state = run([
      START,
      { type: "message.delta", seq: 2, delta: "生成中" },
      {
        type: "run.failed",
        seq: 3,
        error: { code: "model_error", message: "上游 502", retryable: true },
      },
    ]);
    expect(state.phase).toBe("failed");
    expect(state.error).toEqual({ code: "model_error", message: "上游 502", retryable: true });
    const last = state.items[state.items.length - 1];
    expect(last?.kind === "assistant" && last.streaming).toBe(false);
  });
});

describe("historyToItems 历史重建", () => {
  const messages: SessionMessage[] = [
    { id: "m1", seq: 1, role: "user", content: "看下时间", tool_calls: null, tool_call_id: null, created_at: "2026-10-24T00:00:00Z" },
    {
      id: "m2", seq: 2, role: "assistant", content: null,
      tool_calls: [{ id: "t_1", type: "function", function: { name: "get_time", arguments: "{}" } }],
      tool_call_id: null, created_at: "2026-10-24T00:00:01Z",
    },
    { id: "m3", seq: 3, role: "tool", content: "utc=…", tool_calls: null, tool_call_id: "t_1", created_at: "2026-10-24T00:00:01Z" },
    { id: "m4", seq: 4, role: "assistant", content: "当前 UTC 时间是…", tool_calls: null, tool_call_id: null, created_at: "2026-10-24T00:00:02Z" },
    { id: "m5", seq: 5, role: "system", content: "system 不进视图", tool_calls: null, tool_call_id: null, created_at: "2026-10-24T00:00:02Z" },
  ];

  it("user/assistant/tool 映射为气泡与工具卡，system 跳过", () => {
    const items = historyToItems(messages);
    expect(items).toHaveLength(3);
    expect(items[0]?.kind).toBe("user");
    const withTools = items[1];
    if (withTools?.kind !== "assistant") throw new Error("unreachable");
    expect(withTools.tools[0]?.name).toBe("get_time");
    expect(items[2]?.kind === "assistant" && items[2].text).toContain("UTC");
  });
});
