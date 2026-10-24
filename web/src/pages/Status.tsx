import { useQuery } from "@tanstack/react-query";

import { api, health } from "../api/client";
import type { AdminStats } from "../api/types";
import { Badge, Card, ErrorBox, PageTitle, Spinner } from "../components/ui";
import { useKeys } from "../hooks/keys";

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(2)} MB`;
}

export function Status() {
  const { adminKey } = useKeys();
  const live = useQuery({
    queryKey: ["healthz"],
    queryFn: () => health("/healthz"),
    refetchInterval: 15_000,
  });
  const ready = useQuery({
    queryKey: ["readyz"],
    queryFn: () => health("/readyz"),
    refetchInterval: 15_000,
  });
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: () => api<AdminStats>("/v1/admin/stats", adminKey),
  });

  const liveOk = live.data?.status === "ok";
  const readyOk = ready.data?.status === "ready";

  return (
    <div>
      <PageTitle>Status</PageTitle>
      <div className="mb-4 flex gap-3">
        <Card className="flex-1">
          <p className="mb-2 text-xs text-dim">进程（/healthz）</p>
          {live.isLoading ? (
            <Spinner />
          ) : live.error ? (
            <ErrorBox>探测失败</ErrorBox>
          ) : (
            <>
              <Badge tone={liveOk ? "ok" : "bad"}>{liveOk ? "存活" : "异常"}</Badge>
              <p className="mt-2 text-xs text-dim">
                版本 {String(live.data?.version ?? "?")} · 启动 {String(live.data?.uptime_s ?? "?")}s
              </p>
            </>
          )}
        </Card>
        <Card className="flex-1">
          <p className="mb-2 text-xs text-dim">依赖（/readyz）</p>
          {ready.isLoading ? (
            <Spinner />
          ) : ready.error ? (
            <ErrorBox>探测失败</ErrorBox>
          ) : (
            <>
              <Badge tone={readyOk ? "ok" : "bad"}>{readyOk ? "就绪" : "未就绪"}</Badge>
              <p className="mt-2 text-xs text-dim">
                db：{String((ready.data?.checks as Record<string, string>)?.db ?? "?")}
              </p>
            </>
          )}
        </Card>
      </div>
      {stats.isLoading ? (
        <Spinner />
      ) : stats.error ? (
        <ErrorBox>{String(stats.error)}</ErrorBox>
      ) : (
        stats.data && (
          <Card>
            <p className="mb-3 text-xs text-dim">运行概况（admin/stats）</p>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="text-2xl font-semibold">{stats.data.sessions}</p>
                <p className="text-xs text-dim">sessions</p>
              </div>
              <div>
                <p className="text-2xl font-semibold">
                  {Object.values(stats.data.runs_by_status).reduce((a, b) => a + b, 0)}
                </p>
                <p className="text-xs text-dim">
                  runs（{Object.entries(stats.data.runs_by_status)
                    .map(([status, n]) => `${status}:${n}`)
                    .join(" ") || "无"}）
                </p>
              </div>
              <div>
                <p className="text-2xl font-semibold">
                  {stats.data.usage.input_tokens + stats.data.usage.output_tokens}
                </p>
                <p className="text-xs text-dim">tokens 累计</p>
              </div>
              <div>
                <p className="text-2xl font-semibold">${stats.data.usage.cost_usd.toFixed(4)}</p>
                <p className="text-xs text-dim">成本累计 · DB {bytes(stats.data.db_size_bytes)}</p>
              </div>
            </div>
            <p className="mt-3 text-xs text-dim">
              workspace：{stats.data.workspace_root} · Prometheus 指标见 /metrics
            </p>
          </Card>
        )
      )}
    </div>
  );
}
