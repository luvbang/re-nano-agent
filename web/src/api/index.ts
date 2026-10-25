/**
 * 统一客户端门面：real（后端已部署）/ demo（离线演示）。
 * 页面与 hooks 只依赖这里的 ApiClient 接口，后端契约变更时只需改本层。
 */

import { createRealClient } from "./client";
import { createDemoClient } from "./mock";
import { streamRunEvents } from "../sse/run-stream";
import type {
  AdminStats,
  ApiKeyInfo,
  CreatedKey,
  HealthResponse,
  Project,
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
    q?: { limit?: number; beforeSeq?: number },
  ): Promise<SessionMessage[]>;
  createRun(sessionId: string, input: { input: string }): Promise<{ run_id: string }>;
  getRun(runId: string): Promise<RunInfo>;
  cancelRun(runId: string): Promise<RunInfo>;
  listProjects(): Promise<Project[]>;
  createProject(name: string): Promise<Project>;
  listKeys(): Promise<ApiKeyInfo[]>;
  createKey(projectId: string, name: string | null): Promise<CreatedKey>;
  revokeKey(keyId: string): Promise<ApiKeyInfo>;
  usage(q: { dateFrom: string; dateTo: string; group_by: UsageGroupBy }): Promise<UsageResponse>;
  adminStats(): Promise<AdminStats>;
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
      renameSession: (id, title) => demo.renameSession(id, title),
      deleteSession: (id) => demo.deleteSession(id),
      listMessages: (id, q) => demo.listMessages(id, q),
      createRun: (id, input) => demo.createRun(id, input),
      getRun: (id) => demo.getRun(id),
      cancelRun: (id) => demo.cancelRun(id),
      listProjects: () => demo.listProjects(),
      createProject: (name) => demo.createProject(name),
      listKeys: () => demo.listKeys(),
      createKey: (projectId, name) => demo.createKey(projectId, name),
      revokeKey: (id) => demo.revokeKey(id),
      usage: (q) => demo.usage(q),
      adminStats: () => demo.adminStats(),
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
    renameSession: (id, title) => real.renameSession(id, title),
    deleteSession: (id) => real.deleteSession(id),
    listMessages: (id, q) => real.listMessages(id, q),
    createRun: (id, input) => real.createRun(id, input),
    getRun: (id) => real.getRun(id),
    cancelRun: (id) => real.cancelRun(id),
    listProjects: () => real.listProjects(),
    createProject: (name) => real.createProject(name),
    listKeys: () => real.listKeys(),
    createKey: (projectId, name) => real.createKey(projectId, name),
    revokeKey: (id) => real.revokeKey(id),
    usage: (q) => real.usage(q),
    adminStats: () => real.adminStats(),
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
