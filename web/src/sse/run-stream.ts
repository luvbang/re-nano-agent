/**
 * SSE 流解析与传输（web-architecture §4）。
 *
 * 为什么不用 EventSource：无法带 Authorization 头，而我们的认证就是 Bearer key。
 * 解析器按契约产出与事件名同名的对象；传输层负责重连（Last-Event-ID）、
 * 心跳超时（45s 无任何行视为断流）与终态停止。
 */

import type { RunStreamEvent, StreamEventName } from "../api/types";
import { isTerminalEvent } from "../api/types";

export interface RawSSEMessage {
  event?: string;
  data: string;
  id?: string;
}

/** 有状态的 SSE 行解析器：喂入任意切块的文本，产出完整消息（纯逻辑，可直测）。 */
export function createSSEParser() {
  let buffer = "";
  let pendingEvent: string | undefined;
  let pendingData: string[] = [];
  let pendingId: string | undefined;

  function dispatch(): RawSSEMessage | null {
    if (pendingData.length === 0 && pendingEvent === undefined && pendingId === undefined) {
      return null;
    }
    const msg: RawSSEMessage = { data: pendingData.join("\n") };
    if (pendingEvent !== undefined) msg.event = pendingEvent;
    if (pendingId !== undefined) msg.id = pendingId;
    pendingEvent = undefined;
    pendingData = [];
    pendingId = undefined;
    return msg;
  }

  function push(chunk: string): RawSSEMessage[] {
    buffer += chunk;
    const out: RawSSEMessage[] = [];
    let idx: number;
    // 兼容 \r\n 与 \n；行分界即消息边界（SSE 以空行分隔）
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, "");
      buffer = buffer.slice(idx + 1);
      if (line === "") {
        const msg = dispatch();
        if (msg) out.push(msg);
        continue;
      }
      if (line.startsWith(":")) continue; // 心跳注释行 ": ping"
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") pendingEvent = value;
      else if (field === "data") pendingData.push(value);
      else if (field === "id") pendingId = value;
    }
    return out;
  }

  function end(): RawSSEMessage[] {
    const out = push("\n"); // 结束未换行的最后一行
    const flushed = dispatch(); // 仍挂起的字段（如无结尾空行的 data）按规范派发
    return flushed ? [...out, flushed] : out;
  }

  return { push, end };
}

/** 把 SSE 消息解析为契约事件；event/data 不认识时返回 null（前向兼容）。 */
export function toRunStreamEvent(msg: RawSSEMessage): RunStreamEvent | null {
  if (!msg.event || !msg.data) return null;
  try {
    const payload = JSON.parse(msg.data) as Record<string, unknown>;
    const type = msg.event as StreamEventName;
    if (typeof payload["seq"] !== "number") return null;
    return { type, ...(payload as object) } as RunStreamEvent;
  } catch {
    return null;
  }
}

export interface StreamOptions {
  apiKey: string;
  baseUrl?: string;
  lastEventId?: number;
  signal?: AbortSignal;
  /** 心跳超时（ms）：超过该时长未收到任何行即断开重连 */
  heartbeatTimeoutMs?: number;
  maxRetries?: number;
  /** 每次重连的退避基数（ms），实际等待 = base * attempt */
  retryBackoffMs?: number;
}

const TERMINAL_STOP = Symbol("terminal");

/**
 * 订阅一个 run 的事件流直到终态（run.completed / run.failed）。
 * 断流自动带 Last-Event-ID 重连；契约：delta 不补发，completed 全文才是真相。
 */
export async function* streamRunEvents(
  runId: string,
  opts: StreamOptions,
): AsyncGenerator<RunStreamEvent, void, unknown> {
  const {
    apiKey,
    baseUrl = "",
    lastEventId = 0,
    signal,
    heartbeatTimeoutMs = 45_000,
    maxRetries = 5,
    retryBackoffMs = 500,
  } = opts;
  let lastSeq = lastEventId;
  let attempt = 0;

  while (true) {
    signal?.throwIfAborted();
    try {
      const terminal = yield* readOnce(runId, {
        apiKey,
        baseUrl,
        lastSeq,
        signal,
        heartbeatTimeoutMs,
        onSeq: (seq) => {
          lastSeq = seq;
          attempt = 0; // 收到事件说明链路健康，重连计数清零
        },
      });
      if (terminal === TERMINAL_STOP) return;
      attempt += 1;
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof HttpError && (err.status === 401 || err.status === 403 || err.status === 404)) {
        throw err; // 不可重试的错误直接上抛（由调用方清理 key / 提示）
      }
      attempt += 1;
    }
    if (attempt > maxRetries) throw new Error("stream: exceeded max retries");
    const backoff = Math.min(retryBackoffMs * 2 ** (attempt - 1), 8_000);
    await sleep(backoff, signal);
  }
}

async function* readOnce(
  runId: string,
  opts: {
    apiKey: string;
    baseUrl: string;
    lastSeq: number;
    signal?: AbortSignal;
    heartbeatTimeoutMs: number;
    onSeq: (seq: number) => void;
  },
): AsyncGenerator<RunStreamEvent, typeof TERMINAL_STOP | undefined, unknown> {
  const headers: Record<string, string> = { Authorization: `Bearer ${opts.apiKey}` };
  if (opts.lastSeq > 0) headers["Last-Event-ID"] = String(opts.lastSeq);
  const resp = await fetch(`${opts.baseUrl}/v1/runs/${runId}/events`, {
    headers,
    signal: opts.signal,
  });
  if (!resp.ok || !resp.body) {
    throw new HttpError(resp.status, `stream http ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const kick = () => {
    if (watchdog !== undefined) clearTimeout(watchdog);
    watchdog = setTimeout(() => void reader.cancel(), opts.heartbeatTimeoutMs);
  };
  kick();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      kick();
      for (const raw of parser.push(decoder.decode(value, { stream: true }))) {
        const ev = toRunStreamEvent(raw);
        if (!ev) continue;
        opts.onSeq(ev.seq);
        yield ev;
        if (isTerminalEvent(ev)) return TERMINAL_STOP;
      }
    }
    for (const raw of parser.end()) {
      const ev = toRunStreamEvent(raw);
      if (!ev) continue;
      opts.onSeq(ev.seq);
      yield ev;
      if (isTerminalEvent(ev)) return TERMINAL_STOP;
    }
  } finally {
    if (watchdog !== undefined) clearTimeout(watchdog);
  }
  return undefined; // 正常 EOF（服务端关流）：由外层决定是否重连
}

export class HttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    if (signal) {
      if (signal.aborted) onAbort();
      else signal.addEventListener("abort", onAbort, { once: true });
    }
  });
}
