/**
 * API 类型定义 —— 手写自 docs/api-contract.md（M0 冻结的契约）。
 * M3 落地 /openapi.json 后可切 openapi-typescript 生成（web-architecture §3），
 * 字段名与契约一致，届时替换本文件即可。
 */

export interface Usage {
  input_tokens: number;
  output_tokens: number;
}

export interface ToolCallWire {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export type MessageRole = "system" | "user" | "assistant" | "tool" | "summary";

export interface SessionInfo {
  id: string;
  external_user_id: string | null;
  title: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SessionMessage {
  id: string;
  seq: number;
  role: MessageRole;
  content: string | null;
  tool_calls: ToolCallWire[] | null;
  tool_call_id: string | null;
  created_at: string;
}

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface RunError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface RunInfo {
  id: string;
  session_id: string;
  status: RunStatus;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  error: RunError | null;
  created_at: string;
  finished_at: string | null;
}

export interface ApiKeyInfo {
  id: string;
  key_prefix: string;
  name: string | null;
  scopes: string;
  rate_limit_per_min: number;
  revoked_at: string | null;
  created_at: string;
}

/** 创建 key 的响应：secret 只出现这一次（后端只存 hash，契约 §5.1） */
export interface CreatedKey {
  key: ApiKeyInfo;
  secret: string;
}

export type UsageGroupBy = "day" | "model";

export interface UsageItem {
  group: string;
  runs: number;
  input_tokens: number;
  output_tokens: number;
}

export interface UsageResponse {
  from: string;
  to: string;
  group_by: UsageGroupBy;
  items: UsageItem[];
}

export interface HealthResponse {
  status: string;
  version: string;
  uptime_s: number;
}

export interface ReadyResponse {
  status: string;
  checks: Record<string, string>;
}

/** SSE 事件（契约 §3；seq 单调递增，message.completed 全文是真相） */
export type RunStreamEvent =
  | { type: "run.started"; seq: number; run_id: string; session_id: string }
  | { type: "message.delta"; seq: number; delta: string }
  | { type: "reasoning.delta"; seq: number; delta: string }
  | {
      type: "tool.started";
      seq: number;
      tool_call_id: string;
      name: string;
      args: Record<string, unknown>;
    }
  | {
      type: "tool.completed";
      seq: number;
      tool_call_id: string;
      name: string;
      status: "ok" | "error";
      duration_ms: number;
    }
  | { type: "message.completed"; seq: number; content: string; usage: Usage }
  | { type: "run.completed"; seq: number; usage: Usage }
  | { type: "run.failed"; seq: number; error: RunError };

export type StreamEventName = RunStreamEvent["type"];

export function isTerminalEvent(ev: RunStreamEvent): boolean {
  return ev.type === "run.completed" || ev.type === "run.failed";
}
