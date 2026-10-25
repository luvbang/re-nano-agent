/**
 * API 类型定义 —— 对齐 main 后端 /openapi.json（有快照守护 tests/fixtures/openapi.json，
 * 字段名以它为准）。SSE 事件负载与 docs/api-contract.md §3/§5 一致。
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
  project_id: string;
  external_user_id: string | null;
  title: string | null;
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

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface ApiKeyInfo {
  id: string;
  project_id: string;
  key_prefix: string;
  name: string | null;
  scopes: string;
  rate_limit_per_min: number;
  revoked_at: string | null;
  created_at: string;
}

/** 创建 key 的响应：明文只出现这一次（后端只存 hash，契约 §5.1） */
export interface CreatedKey {
  key: string;
  detail: ApiKeyInfo;
}

export type UsageGroupBy = "day" | "model";

export interface UsageItem {
  bucket: string;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface UsageResponse {
  group_by: UsageGroupBy;
  items: UsageItem[];
}

export interface AdminStats {
  runs_by_status: Record<string, number>;
  sessions: number;
  usage: { records: number; input_tokens: number; output_tokens: number; cost_usd: number };
  db_size_bytes: number;
  workspace_root: string;
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
      /** v0.2-4：工具输出预览（后端封顶 2000 字符）；旧事件可能缺省 */
      result?: string;
    }
  | { type: "message.completed"; seq: number; content: string; usage: Usage }
  | { type: "run.completed"; seq: number; usage: Usage }
  | { type: "run.failed"; seq: number; error: RunError }
  | { type: "run.cancelled"; seq: number; run_id: string; reason: string };

export type StreamEventName = RunStreamEvent["type"];

export function isTerminalEvent(ev: RunStreamEvent): boolean {
  return ev.type === "run.completed" || ev.type === "run.failed" || ev.type === "run.cancelled";
}
