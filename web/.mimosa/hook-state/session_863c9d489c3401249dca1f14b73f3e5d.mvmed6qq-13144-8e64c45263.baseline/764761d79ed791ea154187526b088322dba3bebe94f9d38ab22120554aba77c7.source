/**
 * 统一客户端门面：real（后端已部署）/ demo（离线演示）。
 * 页面与 hooks 只依赖这里的 ApiClient 接口，M3 后端就绪后无需改页面代码。
 */

import { createRealClient } from "./client";
import { createDemoClient } from "./mock";
import { streamRunEvents } from "../sse/run-stream";
import type {
  ApiKeyInfo,
  CreatedKey,
  HealthResponse,
  ReadyResponse,
  RunInfo,
  RunStreamEvent,
  SessionInfo,
  SessionMessage,
  UsageGroupBy,
  UsageResponse,
} from "./types";

export type ClientMode = "real" | "demo";

export interface StreamRunEventsFn {
  (runId: string, opts: { signal?: AbortSignal }): AsyncGenerator<RunStreamEvent, void, unknown>;
}

export interface ApiClient {
  mode: ClientMode;
  listSessions(limit?: number): Promise<SessionInfo[]>;
  createSession(input: { title?: string; external_user_id?: string }): Promise<SessionInfo>;
  getSession(id: string): Promise<SessionInfo>;
  listMessages(
    sessionId: string,
    q?: { limit?: number; before?: number },
  ): Promise<SessionMessage[]>;
  createRun(sessionId: string, input: { input: string }): Promise<{ run_id: string }>;
  getRun(runId: string): Promise<RunInfo>;
  cancelRun(runId: string): Promise<RunInfo>;
  listKeys(): Promise<ApiKeyInfo[]>;
  createKey(name: string | null): Promise<CreatedKey>;
  revokeKey(keyId: string): Promise<void>;
  usage(q: { from: string; to: string; group_by: UsageGroupBy }): Promise<UsageResponse>;
  health(): Promise<HealthResponse>;
  ready(): Promise<ReadyResponse>;
  streamRunEvents: StreamRunEventsFn;
}

export function createApiClient(
  mode: ClientMode,
  auth: { apiKey: string; baseUrl?: string; onUnauthorized?: () => void },
): ApiClient {
  if (mode === "demo") {
    const demo = createDemoClient();
    return {
      mode: demo.mode,
      listSessions: (limit?: number) => demo.listSessions(limit),
      createSession: (input) => demo.createSession(input),
      getSession: (id) => demo.getSession(id),
      listMessages: (id, q) => demo.listMessages(id, q),
      createRun: (id, input) => demo.createRun(id, input),
      getRun: (id) => demo.getRun(id),
      cancelRun: (id) => demo.cancelRun(id),
      listKeys: () => demo.listKeys(),
      createKey: (name) => demo.createKey(name),
      revokeKey: (id) => demo.revokeKey(id),
      usage: (q) => demo.usage(q),
      health: () => demo.health(),
      ready: () => demo.ready(),
      streamRunEvents: (runId, opts) => demo.streamRunEvents(runId, opts),
    };
  }
  const real = createRealClient({
    apiKey: auth.apiKey,
    baseUrl: auth.baseUrl,
    onUnauthorized: auth.onUnauthorized,
  });
  return {
    mode: real.mode,
    listSessions: (limit?: number) => real.listSessions(limit),
    createSession: (input) => real.createSession(input),
    getSession: (id) => real.getSession(id),
    listMessages: (id, q) => real.listMessages(id, q),
    createRun: (id, input) => real.createRun(id, input),
    getRun: (id) => real.getRun(id),
    cancelRun: (id) => real.cancelRun(id),
    listKeys: () => real.listKeys(),
    createKey: (name) => real.createKey(name),
    revokeKey: (id) => real.revokeKey(id),
    usage: (q) => real.usage(q),
    health: () => real.health(),
    ready: () => real.ready(),
    streamRunEvents: (runId, opts) =>
      streamRunEvents(runId, {
        apiKey: auth.apiKey,
        baseUrl: auth.baseUrl,
        signal: opts.signal,
      }),
  };
}
