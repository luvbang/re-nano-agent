/** SSE 消费：fetch 流解析（EventSource 带不了 Authorization 头）+ 断线重连。 */

import type { StreamEvent } from "./types";

const RECONNECT_MAX = 3;

export async function* streamRun(
  runId: string,
  key: string,
  lastSeq = 0,
): AsyncGenerator<StreamEvent> {
  let cursor = lastSeq;
  for (let attempt = 0; attempt <= RECONNECT_MAX; attempt += 1) {
    let closed = false;
    try {
      const response = await fetch(`/v1/runs/${runId}/events`, {
        headers: {
          Authorization: `Bearer ${key}`,
          Accept: "text/event-stream",
          ...(cursor > 0 ? { "Last-Event-ID": String(cursor) } : {}),
        },
      });
      if (!response.ok || !response.body) {
        throw new Error(`SSE HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let split = buffer.indexOf("\n\n");
        while (split >= 0) {
          const block = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          split = buffer.indexOf("\n\n");
          const event = parseBlock(block);
          if (event && event.seq > cursor) {
            cursor = event.seq;
            yield event;
          }
        }
      }
      closed = true;
      return; // 服务端正常收尾
    } catch (cause) {
      if (attempt === RECONNECT_MAX) {
        throw new Error(`SSE 断流：${String(cause)}`);
      }
      await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
      void closed;
    }
  }
}

export function parseBlock(block: string): StreamEvent | null {
  let type = "";
  let seq = 0;
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) type = line.slice(7).trim();
    else if (line.startsWith("id: ")) seq = Number.parseInt(line.slice(4).trim(), 10) || 0;
    else if (line.startsWith("data: ")) data = line.slice(6);
  }
  if (!type && !data) return null;
  let payload: Record<string, unknown> = {};
  try {
    payload = data ? (JSON.parse(data) as Record<string, unknown>) : {};
  } catch {
    payload = { raw: data };
  }
  return { seq, type: type || "message", data: payload };
}
