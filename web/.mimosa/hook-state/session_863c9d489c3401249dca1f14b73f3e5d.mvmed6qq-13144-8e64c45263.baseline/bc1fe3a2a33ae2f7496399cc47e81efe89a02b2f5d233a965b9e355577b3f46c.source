/** Usage：按天/按模型聚合图表，日期范围查询（消费 GET /v1/usage）。 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { UsageByDayChart, UsageByModelChart } from "../components/UsageChart";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { daysAgoISO, todayISO } from "../lib/format";
import type { UsageGroupBy } from "../api/types";

export function UsagePage() {
  const { client, mode } = useAdminKey();
  const [from, setFrom] = useState(daysAgoISO(14));
  const [to, setTo] = useState(todayISO());
  const [groupBy, setGroupBy] = useState<UsageGroupBy>("day");
  const [query, setQuery] = useState({ from, to, group_by: groupBy });

  const usageQuery = useQuery({
    queryKey: ["usage", mode, query],
    queryFn: () => client.usage(query),
  });

  const apply = () => setQuery({ from, to, group_by: groupBy });

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">{copy.usage.title}</h1>

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <label className="text-xs text-zinc-400">
          {copy.usage.from}
          <Input type="date" className="mt-1" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="text-xs text-zinc-400">
          {copy.usage.to}
          <Input type="date" className="mt-1" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <div className="flex gap-1">
          {(["day", "model"] as const).map((g) => (
            <Button
              key={g}
              variant={groupBy === g ? "primary" : "ghost"}
              onClick={() => setGroupBy(g)}
            >
              {g === "day" ? copy.usage.byDay : copy.usage.byModel}
            </Button>
          ))}
        </div>
        <Button onClick={apply}>{copy.usage.query}</Button>
      </Card>

      {usageQuery.isPending ? (
        <LoadingState />
      ) : usageQuery.isError ? (
        <ErrorState message={usageQuery.error.message} onRetry={() => void usageQuery.refetch()} />
      ) : (
        <Card className="p-4">
          {query.group_by === "day" ? (
            <UsageByDayChart items={usageQuery.data.items} />
          ) : (
            <UsageByModelChart items={usageQuery.data.items} />
          )}
        </Card>
      )}
    </div>
  );
}
