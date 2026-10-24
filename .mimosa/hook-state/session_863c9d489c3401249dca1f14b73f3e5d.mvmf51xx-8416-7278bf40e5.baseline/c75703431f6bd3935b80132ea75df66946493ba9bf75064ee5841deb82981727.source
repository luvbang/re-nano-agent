/**
 * useRunStream：Playground 的流式状态机（web-architecture §3——不进全局 store）。
 *
 * 职责：send(text) → createRun → streamRunEvents → 投影累积 → 终态；
 * cancel() 中止流并调用取消端点。状态本体是 RunProjection（纯函数投影），
 * 这里只做异步编排，不做业务计算。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api";
import {
  applyEvent,
  initialProjection,
  type RunProjection,
} from "../projection/run-projection";

export interface UseRunStreamResult {
  projection: RunProjection;
  sending: boolean;
  send: (text: string) => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
}

export function useRunStream(client: ApiClient, sessionId: string | null): UseRunStreamResult {
  const [projection, setProjection] = useState<RunProjection>(initialProjection);
  const [sending, setSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);
  const sessionRef = useRef<string | null>(sessionId);
  sessionRef.current = sessionId;

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const send = useCallback(
    async (text: string) => {
      const sid = sessionRef.current;
      if (!sid || !text.trim() || sending) return;
      setSending(true);
      setProjection({
        ...initialProjection(),
        phase: "streaming",
        items: [{ kind: "user", text }],
      });
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const { run_id: runId } = await client.createRun(sid, { input: text });
        if (controller.signal.aborted) return;
        runIdRef.current = runId;
        for await (const ev of client.streamRunEvents(runId, { signal: controller.signal })) {
          setProjection((prev) => applyEvent(prev, ev));
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setProjection((prev) => ({
            ...prev,
            phase: "failed",
            error: {
              code: "network_error",
              message: err instanceof Error ? err.message : String(err),
              retryable: true,
            },
          }));
        }
      } finally {
        setSending(false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [client, sending],
  );

  const cancel = useCallback(async () => {
    abortRef.current?.abort();
    const runId = runIdRef.current;
    if (runId) {
      try {
        await client.cancelRun(runId);
      } catch {
        // 取消失败不阻塞 UI；run 状态由服务端收敛
      }
    }
    runIdRef.current = null;
    setSending(false);
  }, [client]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    runIdRef.current = null;
    setSending(false);
    setProjection(initialProjection());
  }, []);

  return { projection, sending, send, cancel, reset };
}
