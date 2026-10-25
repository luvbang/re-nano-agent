/** Usage：按天/按模型聚合图表，日期范围即改即查，附汇总卡片（消费 GET /v1/usage）。 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { UsageByDayChart, UsageByModelChart } from "../components/UsageChart";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { formatCost, formatTokens } from "../lib/format";
import { daysAgoISO, todayISO } from "../lib/format";
import type { UsageGroupBy } from "../api/types";

export function UsagePage() {
  const { client, mode } = useAdminKey();
  const [from, setFrom] = useState(daysAgoISO(14));
  const [to, setTo] = useState(todayISO());
  const [groupBy, setGroupBy] = useState<UsageGroupBy>("day");

  const usageQuery = useQuery({
    queryKey: ["usage", mode, from, to, groupBy],
    queryFn: () => client.usage({ dateFrom: from, dateTo: to, group_by: groupBy }),
    placeholderData: (prev) => prev, // 换查询条件时保留旧图，避免整页闪加载态
  });

  const items = usageQuery.data?.items ?? [];
  const totalRuns = items.reduce((n, it) => n + it.runs, 0);
  const totalTokens = items.reduce((n, it) => n + it.input_tokens + it.output_tokens, 0);
  const totalCost = items.reduce((n, it) => n + it.cost_usd, 0);

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
        {usageQuery.isFetching ? <span className="text-xs text-zinc-500">{copy.state.loading}</span> : null}
      </Card>

      {!usageQuery.isPending && !usageQuery.isError && items.length > 0 ? (
        <div className="grid grid-cols-3 gap-3">
          <Card className="p-3 text-center">
            <div className="text-xs text-zinc-500">{copy.usage.totalRuns}</div>
            <div className="mt-1 text-lg font-semibold text-zinc-100">{totalRuns}</div>
          </Card>
          <Card className="p-3 text-center">
            <div className="text-xs text-zinc-500">{copy.usage.totalTokens}</div>
            <div className="mt-1 text-lg font-semibold text-zinc-100">{formatTokens(totalTokens)}</div>
          </Card>
          <Card className="p-3 text-center">
            <div className="text-xs text-zinc-500">{copy.usage.totalCost}</div>
            <div className="mt-1 text-lg font-semibold text-zinc-100">{formatCost(totalCost)}</div>
          </Card>
        </div>
      ) : null}

      {usageQuery.isPending ? (
        <LoadingState />
      ) : usageQuery.isError ? (
        <ErrorState message={usageQuery.error.message} onRetry={() => void usageQuery.refetch()} />
      ) : (
        <Card className="p-4">
          {groupBy === "day" ? (
            <UsageByDayChart items={items} />
          ) : (
            <UsageByModelChart items={items} />
          )}
        </Card>
      )}
    </div>
  );
}
