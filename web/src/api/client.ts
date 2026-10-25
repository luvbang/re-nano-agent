/**
 * 真实后端客户端：fetch 封装（Bearer 注入、错误信封 → 异常、401/403 清 key 跳登录）。
 * 端点形状对齐 main 后端实现（/openapi.json 有快照守护）。
 */

import type {
  AdminStats,
  ApiKeyInfo,
  CreatedKey,
  HealthResponse,
  Project,
  ReadyResponse,
  RunInfo,
  SessionInfo,
  SessionMessage,
  UsageGroupBy,
  UsageResponse,
} from "./types";

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export interface UnauthorizedHandler {
  (): void;
}

export interface RealClientOptions {
  apiKey: string;
  baseUrl?: string;
  onUnauthorized?: UnauthorizedHandler;
}

async function request<T>(
  path: string,
  opts: RealClientOptions,
  init?: RequestInit,
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${opts.baseUrl ?? ""}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${opts.apiKey}`,
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiRequestError(0, "network_error", "无法连接后端", false);
  }
  if (resp.status === 401 || resp.status === 403) {
    opts.onUnauthorized?.();
    throw new ApiRequestError(resp.status, resp.status === 401 ? "unauthorized" : "forbidden",
      "Key 无效或无权访问", false);
  }
  if (!resp.ok) {
    let code = "internal";
    let message = `HTTP ${resp.status}`;
    let retryable = false;
    try {
      const body = (await resp.json()) as { error?: { code?: string; message?: string; retryable?: boolean } };
      if (body.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        retryable = body.error.retryable ?? retryable;
      }
    } catch {
      // 非 JSON 错误体，用默认值
    }
    throw new ApiRequestError(resp.status, code, message, retryable);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export function createRealClient(opts: RealClientOptions) {
  return {
    mode: "real" as const,
    listSessions: (limit = 50) =>
      request<SessionInfo[]>(`/v1/sessions?limit=${limit}`, opts),
    createSession: (input: { title?: string; external_user_id?: string }) =>
      request<SessionInfo>("/v1/sessions", opts, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    getSession: (id: string) => request<SessionInfo>(`/v1/sessions/${id}`, opts),
    listMessages: (sessionId: string, q: { limit?: number; beforeSeq?: number } = {}) => {
      const params = new URLSearchParams();
      if (q.limit) params.set("limit", String(q.limit));
      if (q.beforeSeq) params.set("before_seq", String(q.beforeSeq));
      const qs = params.toString();
      // 后端返回 MessagePage{items, has_more}；控制台一次取 limit 内的全量，展开为有序数组
      return request<{ items: SessionMessage[]; has_more: boolean }>(
        `/v1/sessions/${sessionId}/messages${qs ? `?${qs}` : ""}`,
        opts,
      ).then((page) => page.items);
    },
    createRun: (sessionId: string, input: { input: string }) =>
      request<{ run_id: string }>(`/v1/sessions/${sessionId}/runs`, opts, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    getRun: (runId: string) => request<RunInfo>(`/v1/runs/${runId}`, opts),
    cancelRun: (runId: string) =>
      request<RunInfo>(`/v1/runs/${runId}/cancel`, opts, { method: "POST" }),
    listProjects: () => request<Project[]>("/v1/admin/projects", opts),
    createProject: (name: string) =>
      request<Project>("/v1/admin/projects", opts, {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    listKeys: () => request<ApiKeyInfo[]>("/v1/admin/keys", opts),
    createKey: (projectId: string, name: string | null) =>
      request<CreatedKey>("/v1/admin/keys", opts, {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, name }),
      }),
    revokeKey: (keyId: string) =>
      request<ApiKeyInfo>(`/v1/admin/keys/${keyId}/revoke`, opts, { method: "POST" }),
    usage: (q: { dateFrom: string; dateTo: string; group_by: UsageGroupBy }) => {
      const params = new URLSearchParams({
        group_by: q.group_by,
        date_from: q.dateFrom,
        date_to: q.dateTo,
      });
      return request<UsageResponse>(`/v1/usage?${params.toString()}`, opts);
    },
    adminStats: () => request<AdminStats>("/v1/admin/stats", opts),
    health: () => request<HealthResponse>("/healthz", opts),
    ready: () => request<ReadyResponse>("/readyz", opts),
  };
}

export type RealClient = ReturnType<typeof createRealClient>;

/** SSE 订阅复用 sse/run-stream（见该文件；单独导出便于 mock 替换）。 */
export { streamRunEvents } from "../sse/run-stream";
