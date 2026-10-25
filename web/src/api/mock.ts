/**
 * 离线演示客户端：后端未部署时的全功能 mock 后端
 * （web-architecture §7“后端先行的假数据”在纯前端侧的等价物）。
 *
 * 数据在内存中（标签页刷新即重置）；事件流按契约语义脚本化回放，
 * 含工具调用回路、逐字 delta 与 message.completed 全文覆盖。
 * 接口与真实客户端完全一致（api/index.ts 的 ApiClient）。
 */

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

let seqCounter = 100;
function nextId(prefix: string): string {
  seqCounter += 1;
  return `${prefix}_demo_${seqCounter.toString(36)}`;
}

function nowISO(): string {
  return new Date().toISOString();
}

interface DemoState {
  projects: Project[];
  sessions: SessionInfo[];
  messages: Map<string, SessionMessage[]>;
  keys: ApiKeyInfo[];
  runs: Map<string, { runId: string; sessionId: string; input: string; status: RunInfo["status"] }>;
}

function seed(): DemoState {
  const p1: Project = {
    id: "p_demo_main",
    name: "默认项目",
    created_at: new Date(Date.now() - 86_400_000 * 30).toISOString(),
  };
  const s1: SessionInfo = {
    id: "s_demo_alpha",
    project_id: p1.id,
    external_user_id: "u_1024",
    title: "部署排障",
    created_at: new Date(Date.now() - 86_400_000 * 2).toISOString(),
    updated_at: new Date(Date.now() - 86_400_000).toISOString(),
  };
  const s2: SessionInfo = {
    id: "s_demo_beta",
    project_id: p1.id,
    external_user_id: null,
    title: "文档问答",
    created_at: new Date(Date.now() - 86_400_000).toISOString(),
    updated_at: new Date(Date.now() - 3_600_000).toISOString(),
  };
  const msgs1: SessionMessage[] = [
    {
      id: nextId("m"), seq: 1, role: "user", content: "容器里 agentd 起不来，日志怎么看？",
      tool_calls: null, tool_call_id: null, created_at: s1.created_at,
    },
    {
      id: nextId("m"), seq: 2, role: "assistant",
      content: "先看 `docker compose logs -f app`。若出现 database is locked，"
        + "确认只有一个实例在写同一 data 目录；WAL 模式下备份进程只读不冲突。",
      tool_calls: null, tool_call_id: null, created_at: s1.created_at,
    },
    {
      id: nextId("m"), seq: 3, role: "user", content: "好，我试试。顺便看看当前时间对不对",
      tool_calls: null, tool_call_id: null, created_at: s1.updated_at,
    },
    {
      id: nextId("m"), seq: 4, role: "assistant",
      content: "已通过 get_time 查询，容器时间为 UTC。注意宿主机与容器时区差异。",
      tool_calls: [
        { id: "t_demo_1", type: "function", function: { name: "get_time", arguments: "{}" } },
      ],
      tool_call_id: null,
      created_at: s1.updated_at,
    },
    {
      id: nextId("m"), seq: 5, role: "tool", content: "utc=… local=…",
      tool_calls: null, tool_call_id: "t_demo_1", created_at: s1.updated_at,
    },
  ];
  const msgs2: SessionMessage[] = [
    {
      id: nextId("m"), seq: 1, role: "user", content: "v0.1 的范围里包含多用户吗？",
      tool_calls: null, tool_call_id: null, created_at: s2.created_at,
    },
    {
      id: nextId("m"), seq: 2, role: "assistant",
      content: "不包含。v0.1 是单管理员的运行时，多租户排到 v0.2 之后（V0.1-SCOPE §1）。",
      tool_calls: null, tool_call_id: null, created_at: s2.created_at,
    },
  ];
  const keys: ApiKeyInfo[] = [
    {
      id: "k_demo_1", project_id: p1.id, key_prefix: "agd_demo1", name: "playground 集成",
      scopes: "core", rate_limit_per_min: 60, revoked_at: null,
      created_at: new Date(Date.now() - 86_400_000 * 7).toISOString(),
    },
    {
      id: "k_demo_2", project_id: p1.id, key_prefix: "agd_demo2", name: "CI 冒烟",
      scopes: "core", rate_limit_per_min: 10, revoked_at: null,
      created_at: new Date(Date.now() - 86_400_000 * 2).toISOString(),
    },
  ];
  return {
    projects: [p1],
    sessions: [s1, s2],
    messages: new Map([[s1.id, msgs1], [s2.id, msgs2]]),
    keys,
    runs: new Map(),
  };
}

const state: DemoState = seed();

const delay = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
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

export function createDemoClient() {
  return {
    mode: "demo" as const,

    async listSessions(limit = 50): Promise<SessionInfo[]> {
      await delay(80);
      return state.sessions.slice(0, limit);
    },
    async createSession(input: { title?: string; external_user_id?: string }): Promise<SessionInfo> {
      await delay(60);
      const s: SessionInfo = {
        id: nextId("s"),
        project_id: state.projects[0]?.id ?? "p_demo_main",
        external_user_id: input.external_user_id ?? null,
        title: input.title ?? null,
        created_at: nowISO(),
        updated_at: nowISO(),
      };
      state.sessions.unshift(s);
      state.messages.set(s.id, []);
      return s;
    },
    async getSession(id: string): Promise<SessionInfo> {
      const s = state.sessions.find((x) => x.id === id);
      if (!s) throw new Error("not_found");
      return s;
    },
    async renameSession(id: string, title: string): Promise<SessionInfo> {
      await delay(40);
      const s = state.sessions.find((x) => x.id === id);
      if (!s) throw new Error("not_found");
      s.title = title;
      s.updated_at = nowISO();
      return s;
    },
    async deleteSession(id: string): Promise<void> {
      await delay(40);
      const index = state.sessions.findIndex((x) => x.id === id);
      if (index < 0) throw new Error("not_found");
      state.sessions.splice(index, 1);
      state.messages.delete(id);
    },
    async listMessages(
      sessionId: string,
      q: { limit?: number; beforeSeq?: number } = {},
    ): Promise<SessionMessage[]> {
      await delay(60);
      const all = state.messages.get(sessionId) ?? [];
      const filtered = q.beforeSeq ? all.filter((m) => m.seq < q.beforeSeq!) : all;
      return filtered.slice(-(q.limit ?? 100));
    },
    async createRun(sessionId: string, input: { input: string; model?: string }): Promise<{ run_id: string }> {
      await delay(40);
      const runId = nextId("r");
      state.runs.set(runId, { runId, sessionId, input: input.input, status: "running" });
      return { run_id: runId };
    },
    async listModels(): Promise<{ id: string; object: string; tools: boolean }[]> {
      await delay(30);
      return [{ id: "maple-flash", object: "model", tools: true }];
    },
    async getRun(runId: string): Promise<RunInfo> {
      const run = state.runs.get(runId);
      if (!run) throw new Error("not_found");
      return {
        id: run.runId,
        session_id: run.sessionId,
        status: run.status,
        model: "demo-model",
        input_tokens: 42,
        output_tokens: 128,
        error: null,
        created_at: nowISO(),
        finished_at: run.status === "completed" ? nowISO() : null,
      };
    },
    async cancelRun(runId: string): Promise<RunInfo> {
      const run = state.runs.get(runId);
      if (run) run.status = "cancelled";
      return this.getRun(runId);
    },
    async listProjects(): Promise<Project[]> {
      await delay(60);
      return [...state.projects];
    },
    async createProject(name: string): Promise<Project> {
      await delay(80);
      const p: Project = { id: nextId("p"), name, created_at: nowISO() };
      state.projects.push(p);
      return p;
    },
    async listKeys(): Promise<ApiKeyInfo[]> {
      await delay(80);
      return [...state.keys];
    },
    async createKey(projectId: string, name: string | null): Promise<CreatedKey> {
      await delay(80);
      const project = state.projects.find((p) => p.id === projectId);
      if (!project) throw new Error("not_found");
      const secret = `agd_${Math.random().toString(36).slice(2, 22)}`;
      const key: ApiKeyInfo = {
        id: nextId("k"),
        project_id: projectId,
        key_prefix: secret.slice(0, 8),
        name,
        scopes: "core",
        rate_limit_per_min: 60,
        revoked_at: null,
        created_at: nowISO(),
      };
      state.keys.unshift(key);
      return { key: secret, detail: key };
    },
    async revokeKey(keyId: string): Promise<ApiKeyInfo> {
      await delay(60);
      const k = state.keys.find((x) => x.id === keyId);
      if (!k) throw new Error("not_found");
      k.revoked_at = nowISO();
      return k;
    },
    async usage(q: { dateFrom: string; dateTo: string; group_by: UsageGroupBy }): Promise<UsageResponse> {
      await delay(120);
      const items =
        q.group_by === "day"
          ? buildDaily(q.dateFrom, q.dateTo)
          : [
              { bucket: "gpt-4o-mini", runs: 61, input_tokens: 412_000, output_tokens: 96_000, cost_usd: 0.184 },
              { bucket: "demo-model", runs: 37, input_tokens: 128_000, output_tokens: 51_000, cost_usd: 0.061 },
            ];
      return { group_by: q.group_by, items };
    },
    async adminStats(): Promise<AdminStats> {
      await delay(80);
      return {
        runs_by_status: { completed: 86, failed: 3, cancelled: 2, running: 1 },
        sessions: state.sessions.length,
        usage: { records: 98, input_tokens: 540_000, output_tokens: 147_000, cost_usd: 0.245 },
        db_size_bytes: 1_572_864,
        workspace_root: "（演示模式）",
      };
    },
    async health(): Promise<HealthResponse> {
      return { status: "ok", version: "0.1.0", uptime_s: 36_612 };
    },
    async ready(): Promise<ReadyResponse> {
      return { status: "ready", checks: { db: "ok" } };
    },

    /** 脚本化事件流（契约语义：delta → tool → completed 全文 → run 终态） */
    async *streamRunEvents(
      runId: string,
      opts: { signal?: AbortSignal } = {},
    ): AsyncGenerator<RunStreamEvent, void, unknown> {
      const run = state.runs.get(runId);
      if (!run) throw new Error("not_found");
      const { signal } = opts;
      let seq = 0;
      // 分配式 Omit：对联合类型逐成员去掉 seq，避免公共属性坍缩
      type DistributiveOmit<T, K extends keyof never> = T extends unknown ? Omit<T, K> : never;
      const ev = (e: DistributiveOmit<RunStreamEvent, "seq">): RunStreamEvent =>
        ({ seq: ++seq, ...e }) as RunStreamEvent;
      const fail = run.input.includes("失败");
      try {
        await delay(120, signal);
        yield ev({ type: "run.started", run_id: runId, session_id: run.sessionId });
        if (fail) {
          await delay(260, signal);
          yield ev({
            type: "run.failed",
            error: { code: "model_error", message: "（演示）上游模型 502", retryable: true },
          });
          state.runs.set(runId, { ...run, status: "failed" });
          return;
        }
        const lead = "好的，我用 ";
        const useTime = !run.input.includes("文件");
        const toolName = useTime ? "get_time" : "write_file";
        for (const piece of chunkText(lead + toolName + " 工具来处理：")) {
          await delay(45, signal);
          yield ev({ type: "message.delta", delta: piece });
        }
        await delay(120, signal);
        yield ev({
          type: "tool.started",
          tool_call_id: `t_${runId.slice(-4)}`,
          name: toolName,
          args: useTime ? {} : { path: "demo.txt", content: run.input },
        });
        await delay(420, signal);
        yield ev({
          type: "tool.completed",
          tool_call_id: `t_${runId.slice(-4)}`,
          name: toolName,
          status: "ok",
          duration_ms: 418,
          result: useTime
            ? `utc=${new Date().toISOString()} local=${new Date().toLocaleString("zh-CN")}`
            : `已写入 workspace/demo.txt（${run.input.length} 字符）`,
        });
        const tail = useTime
          ? `查询完成。当前时间 ${new Date().toLocaleString("zh-CN")}。这是离线演示数据。`
          : `文件已写入 workspace。这是离线演示数据，刷新页面后不保留。`;
        for (const piece of chunkText(tail)) {
          await delay(45, signal);
          yield ev({ type: "message.delta", delta: piece });
        }
        await delay(90, signal);
        const full = lead + toolName + " 工具来处理：" + tail;
        yield ev({ type: "message.completed", content: full, usage: { input_tokens: 42, output_tokens: 128 } });
        await delay(60, signal);
        yield ev({ type: "run.completed", usage: { input_tokens: 42, output_tokens: 128 } });
        state.runs.set(runId, { ...run, status: "completed" });
        // 演示客户端顺手把完整交换写进“历史”（与真实后端一致：含工具调用记录），续聊/刷新后仍可见
        const msgs = state.messages.get(run.sessionId) ?? [];
        const base = msgs.length ? (msgs[msgs.length - 1]?.seq ?? 0) : 0;
        const toolCallId = `t_${runId.slice(-4)}`;
        msgs.push(
          { id: nextId("m"), seq: base + 1, role: "user", content: run.input, tool_calls: null, tool_call_id: null, created_at: nowISO() },
          {
            id: nextId("m"), seq: base + 2, role: "assistant", content: lead + toolName + " 工具来处理：",
            tool_calls: [{ id: toolCallId, type: "function", function: { name: toolName, arguments: "{}" } }],
            tool_call_id: null, created_at: nowISO(),
          },
          { id: nextId("m"), seq: base + 3, role: "tool", content: "(工具结果)", tool_calls: null, tool_call_id: toolCallId, created_at: nowISO() },
          { id: nextId("m"), seq: base + 4, role: "assistant", content: full, tool_calls: null, tool_call_id: null, created_at: nowISO() },
        );
        state.messages.set(run.sessionId, msgs);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          state.runs.set(runId, { ...run, status: "cancelled" });
        }
        throw err;
      }
    },
  };
}

export type DemoClient = ReturnType<typeof createDemoClient>;

function chunkText(text: string): string[] {
  const chunks: string[] = [];
  let i = 0;
  while (i < text.length) {
    const size = 2 + Math.floor(Math.random() * 3);
    chunks.push(text.slice(i, i + size));
    i += size;
  }
  return chunks;
}

function buildDaily(
  from: string,
  to: string,
): { bucket: string; runs: number; input_tokens: number; output_tokens: number; cost_usd: number }[] {
  const items: { bucket: string; runs: number; input_tokens: number; output_tokens: number; cost_usd: number }[] = [];
  const start = new Date(`${from}T00:00:00Z`).getTime();
  const end = new Date(`${to}T00:00:00Z`).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return items;
  for (let t = start; t <= end && items.length < 90; t += 86_400_000) {
    const day = new Date(t).toISOString().slice(0, 10);
    // 确定性伪随机：让图表每天不一样但刷新不变
    const seed = Number(t / 86_400_000) % 13;
    const input = 8_000 + seed * 4_300;
    const output = 2_100 + seed * 1_050;
    items.push({
      bucket: day,
      runs: 2 + ((seed * 7) % 11),
      input_tokens: input,
      output_tokens: output,
      cost_usd: Math.round(((input * 0.15 + output * 0.6) / 1_000_000) * 1e6) / 1e6,
    });
  }
  return items;
}
