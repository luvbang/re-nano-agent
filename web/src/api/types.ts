/** 对齐 docs/api-contract.md 的最小类型集（控制台消费面）。 */

export interface Session {
  id: string;
  project_id: string;
  title: string | null;
  external_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageItem {
  id: string;
  seq: number;
  role: string;
  content: string | null;
  tool_call_id: string | null;
  created_at: string;
}

export interface RunInfo {
  id: string;
  session_id: string;
  status: string;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

export interface ApiKeyRow {
  id: string;
  project_id: string;
  name: string | null;
  key_prefix: string;
  scopes: string;
  rate_limit_per_min: number;
  revoked_at: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface UsageItem {
  bucket: string;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface UsageResponse {
  group_by: "day" | "model";
  items: UsageItem[];
}

export interface AdminStats {
  runs_by_status: Record<string, number>;
  sessions: number;
  usage: { records: number; input_tokens: number; output_tokens: number; cost_usd: number };
  db_size_bytes: number;
  workspace_root: string;
}

export interface StreamEvent {
  seq: number;
  type: string;
  data: Record<string, unknown>;
}
