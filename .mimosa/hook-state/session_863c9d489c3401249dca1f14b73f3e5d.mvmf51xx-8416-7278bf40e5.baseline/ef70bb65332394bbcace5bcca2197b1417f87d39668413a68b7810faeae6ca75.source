/** SSE 解析器测试：切块边界、心跳注释、CRLF、事件/数据/id 字段。 */

import { describe, expect, it } from "vitest";
import { createSSEParser, toRunStreamEvent } from "./run-stream";

function parseAll(chunks: string[]) {
  const parser = createSSEParser();
  const out = chunks.flatMap((c) => parser.push(c));
  return [...out, ...parser.end()];
}

describe("createSSEParser", () => {
  it("完整事件块解析出 event + data + id", () => {
    const msgs = parseAll([
      'event: message.delta\nid: 2\ndata: {"seq":2,"delta":"你"}\n\n',
    ]);
    expect(msgs).toEqual([
      { event: "message.delta", data: '{"seq":2,"delta":"你"}', id: "2" },
    ]);
  });

  it("跨 chunk 撕裂的消息能拼回", () => {
    const msgs = parseAll([
      "event: run.started\ndata: {\"seq\":1,",
      '"run_id":"r_1","session_id":"s_1"',
      "}\n\n",
    ]);
    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.event).toBe("run.started");
    expect(toRunStreamEvent(msgs[0]!)?.type).toBe("run.started");
  });

  it("心跳注释行被忽略", () => {
    const msgs = parseAll([": ping\n\n", 'event: run.completed\ndata: {"seq":9,"usage":{"input_tokens":1,"output_tokens":2}}\n\n']);
    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.event).toBe("run.completed");
  });

  it("多行 data 以换行拼接（SSE 规范）", () => {
    const msgs = parseAll(["event: x\ndata: line1\ndata: line2\n\n"]);
    expect(msgs[0]?.data).toBe("line1\nline2");
  });

  it("CRLF 行尾与无空行结尾的 flush", () => {
    const msgs = parseAll(["event: y\r\ndata: 1\r\n\r\n", "data: 2"]);
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.data).toBe("2");
  });

  it("data 字段前导单个空格剥离", () => {
    const msgs = parseAll(["data: spaced\n\n"]);
    expect(msgs[0]?.data).toBe("spaced");
  });
});

describe("toRunStreamEvent", () => {
  it("非法 JSON / 缺 seq 返回 null（前向兼容）", () => {
    expect(toRunStreamEvent({ event: "message.delta", data: "{oops" })).toBeNull();
    expect(toRunStreamEvent({ event: "message.delta", data: '{"delta":"x"}' })).toBeNull();
    expect(toRunStreamEvent({ data: "{}" })).toBeNull();
  });

  it("契约事件全部可还原", () => {
    const cases = [
      { event: "run.started", data: '{"seq":1,"run_id":"r","session_id":"s"}' },
      { event: "tool.started", data: '{"seq":3,"tool_call_id":"t","name":"echo","args":{}}' },
      { event: "run.failed", data: '{"seq":8,"error":{"code":"timeout","message":"t","retryable":true}}' },
    ];
    for (const c of cases) {
      expect(toRunStreamEvent(c)).not.toBeNull();
    }
  });
});
