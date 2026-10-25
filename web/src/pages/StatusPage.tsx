/** 系统状态：/healthz（进程存活）、/readyz（依赖就绪）与 /v1/admin/stats（运行概况）。 */

import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card } from "../components/ui";
import { copy } from "../lib/copy";
import { formatBytes, formatCost, formatUptime } from "../lib/format";

export function StatusPage() {
  const { client, mode } = useAdminKey();
  const healthQuery = useQuery({
    queryKey: ["health", mode],
    queryFn: () => client.health(),
    refetchInterval: 15_000,
  });
  const readyQuery = useQuery({
    queryKey: ["ready", mode],
    queryFn: () => client.ready(),
    refetchInterval: 15_000,
  });
  const statsQuery = useQuery({
    queryKey: ["stats", mode],
    queryFn: () => client.adminStats(),
    refetchInterval: 15_000,
  });
  const refetchAll = () => {
    void healthQuery.refetch();
    void readyQuery.refetch();
    void statsQuery.refetch();
  };

  if (healthQuery.isPending || readyQuery.isPending) return <LoadingState />;

  const stats = statsQuery.data;

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{copy.status.title}</h1>
        <Button variant="ghost" onClick={refetchAll}>
          {copy.status.refresh}
          {healthQuery.isFetching || readyQuery.isFetching || statsQuery.isFetching ? " …" : ""}
        </Button>
      </div>

      <Card className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-300">{copy.status.healthz}</span>
          {healthQuery.isError ? (
            <Badge tone="error">{healthQuery.error.message}</Badge>
          ) : (
            <Badge tone="success">{healthQuery.data!.status}</Badge>
          )}
        </div>
        {healthQuery.data ? (
          <div className="text-xs text-zinc-500">
            {copy.status.version} {healthQuery.data.version} · {copy.status.uptime}{" "}
            {formatUptime(healthQuery.data.uptime_s)}
          </div>
        ) : null}
      </Card>

      <Card className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-300">{copy.status.readyz}</span>
          {readyQuery.isError ? (
            <Badge tone="error">{readyQuery.error.message}</Badge>
          ) : readyQuery.data!.status === "ready" ? (
            <Badge tone="success">{readyQuery.data!.status}</Badge>
          ) : (
            <Badge tone="warn">{readyQuery.data!.status}</Badge>
          )}
        </div>
        {readyQuery.data ? (
          <div className="space-y-1">
            <div className="text-xs text-zinc-500">{copy.status.checks}</div>
            {Object.entries(readyQuery.data.checks).map(([name, state]) => (
              <div key={name} className="flex items-center gap-2 text-xs">
                <Badge tone={state === "ok" ? "success" : "error"}>{state}</Badge>
                <span className="font-mono text-zinc-400">{name}</span>
              </div>
            ))}
          </div>
        ) : null}
      </Card>

      {stats ? (
        <Card className="space-y-2 p-4">
          <div className="text-sm font-medium text-zinc-200">{copy.status.statsTitle}</div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            {Object.entries(stats.runs_by_status).map(([status, n]) => (
              <div key={status} className="flex items-center gap-2">
                <Badge tone={status === "completed" ? "success" : status === "running" ? "warn" : "neutral"}>
                  {n}
                </Badge>
                <span className="text-zinc-400">{status}</span>
              </div>
            ))}
          </div>
          <div className="text-xs text-zinc-500">
            {copy.status.sessionsCount} {stats.sessions} · {copy.usage.totalCost}{" "}
            {formatCost(stats.usage.cost_usd)} · {copy.status.dbSize} {formatBytes(stats.db_size_bytes)}
          </div>
          <div className="truncate font-mono text-[11px] text-zinc-600">
            {copy.status.workspace}: {stats.workspace_root}
          </div>
        </Card>
      ) : null}

      {healthQuery.isError ? (
        <ErrorState message={copy.errors.network} onRetry={refetchAll} />
      ) : null}
    </div>
  );
}
