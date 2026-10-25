/** 系统状态：/healthz（进程存活）与 /readyz（依赖就绪）。 */

import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Badge, Button, Card } from "../components/ui";
import { copy } from "../lib/copy";
import { formatUptime } from "../lib/format";

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
  const refetchAll = () => {
    void healthQuery.refetch();
    void readyQuery.refetch();
  };

  if (healthQuery.isPending || readyQuery.isPending) return <LoadingState />;

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{copy.status.title}</h1>
        <Button variant="ghost" onClick={refetchAll}>
          {copy.status.refresh}
        </Button>
      </div>

      <Card className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-300">{copy.status.healthz}</span>
          {healthQuery.isError ? (
            <Badge tone="error">{healthQuery.error.message}</Badge>
          ) : (
            <Badge tone="success">{healthQuery.data.status}</Badge>
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
          ) : readyQuery.data.status === "ready" ? (
            <Badge tone="success">{readyQuery.data.status}</Badge>
          ) : (
            <Badge tone="warn">{readyQuery.data.status}</Badge>
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

      {healthQuery.isError ? (
        <ErrorState message={copy.errors.network} onRetry={refetchAll} />
      ) : null}
    </div>
  );
}
