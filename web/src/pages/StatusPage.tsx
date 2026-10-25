/** 系统状态：/healthz（进程存活）、/readyz（依赖就绪）与 /v1/admin/stats（运行概况）。 */

import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card } from "../components/ui";
import { copy } from "../lib/copy";
import { formatBytes, formatCost, formatTime, formatUptime } from "../lib/format";

function Section({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 gap-4 border-t border-line py-7 first:border-t-0 first:pt-0 lg:grid-cols-[300px_1fr] lg:gap-8">
      <div>
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-mut">{desc}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

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
  const freshness = healthQuery.dataUpdatedAt
    ? copy.status.updatedAt(formatTime(new Date(healthQuery.dataUpdatedAt).toISOString()))
    : null;

  return (
    <div className="mx-auto max-w-[1120px] px-5 pb-12 pt-7 sm:px-8">
      {/* 标题行：h1 + 新鲜度戳 + 刷新 */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-white">{copy.status.title}</h1>
        <span className="flex-1" />
        {freshness ? (
          <span className="num hidden text-xs text-mut md:inline">{freshness}</span>
        ) : null}
        <Button variant="text" onClick={refetchAll}>
          {copy.status.refresh}
          {healthQuery.isFetching || readyQuery.isFetching || statsQuery.isFetching ? " …" : ""}
        </Button>
      </div>

      <div className="mt-6">
        <Section title={copy.status.healthz} desc={copy.status.healthzDesc}>
          <Card className="space-y-2 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-ink">{copy.status.healthzSub}</span>
              {healthQuery.isError ? (
                <Badge tone="error">{healthQuery.error.message}</Badge>
              ) : (
                <Badge tone="success">{healthQuery.data!.status}</Badge>
              )}
            </div>
            {healthQuery.data ? (
              <div className="text-sm text-mut">
                {copy.status.version} <span className="num">{healthQuery.data.version}</span> ·{" "}
                {copy.status.uptime} <span className="num">{formatUptime(healthQuery.data.uptime_s)}</span>
              </div>
            ) : null}
          </Card>
        </Section>

        <Section title={copy.status.readyz} desc={copy.status.readyzDesc}>
          <Card className="space-y-2 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-ink">{copy.status.readyzSub}</span>
              {readyQuery.isError ? (
                <Badge tone="error">{readyQuery.error.message}</Badge>
              ) : readyQuery.data!.status === "ready" ? (
                <Badge tone="success">{readyQuery.data!.status}</Badge>
              ) : (
                <Badge tone="warn">{readyQuery.data!.status}</Badge>
              )}
            </div>
            {readyQuery.data ? (
              <div className="space-y-1.5 pt-1">
                {Object.entries(readyQuery.data.checks).map(([name, state]) => (
                  <div key={name} className="flex items-center gap-2 text-sm">
                    <Badge tone={state === "ok" ? "success" : "error"}>{state}</Badge>
                    <span className="num text-ink">{name}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </Card>
        </Section>

        {stats ? (
          <Section title={copy.status.statsTitle} desc={copy.status.statsDesc}>
            <Card className="p-4">
              <div className="grid grid-cols-1 divide-y divide-rule sm:grid-cols-3 sm:divide-x sm:divide-y-0">
                <div className="px-1 py-2 sm:px-4 sm:first:pl-1">
                  <div className="text-xs text-mut">{copy.status.sessionsCount}</div>
                  <div className="num mt-1 text-xl text-white">{stats.sessions}</div>
                </div>
                <div className="px-1 py-2 sm:px-4">
                  <div className="text-xs text-mut">{copy.usage.totalCost}</div>
                  <div className="num mt-1 text-xl font-semibold text-white">
                    {formatCost(stats.usage.cost_usd)}
                  </div>
                </div>
                <div className="px-1 py-2 sm:px-4">
                  <div className="text-xs text-mut">{copy.status.dbSize}</div>
                  <div className="num mt-1 text-xl text-white">{formatBytes(stats.db_size_bytes)}</div>
                </div>
              </div>
              <div className="mt-4 border-t border-rule pt-3">
                <div className="text-xs text-mut">{copy.status.runsByStatus}</div>
                <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1.5">
                  {Object.entries(stats.runs_by_status).map(([status, n]) => (
                    <span key={status} className="text-sm">
                      <span className="num text-white">{n}</span>{" "}
                      <span className="text-mut">{status}</span>
                    </span>
                  ))}
                </div>
              </div>
              <div className="num mt-4 truncate border-t border-rule pt-3 text-xs text-mut">
                {copy.status.workspace}: {stats.workspace_root}
              </div>
            </Card>
          </Section>
        ) : null}

        {healthQuery.isError ? (
          <ErrorState message={copy.errors.network} onRetry={refetchAll} />
        ) : null}
      </div>
    </div>
  );
}
