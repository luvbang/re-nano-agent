/** Usage：按天/按模型聚合图表 + 汇总卡片 + 明细表（占比条）+ CSV 导出（GET /v1/usage）。 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { UsageByDayChart, UsageByModelChart } from "../components/UsageChart";
import { ErrorState, LoadingState } from "../components/StateViews";
import { Button, Card, Input } from "../components/ui";
import { copy } from "../lib/copy";
import { formatCost, formatTokens, usageCsv } from "../lib/format";
import { daysAgoISO, todayISO } from "../lib/format";
import type { UsageGroupBy, UsageItem } from "../api/types";

function downloadCsv(items: UsageItem[], bucketLabel: string, filename: string) {
  const blob = new Blob([`\ufeff${usageCsv(items, bucketLabel)}`], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function UsageDetailTable({ items, groupBy }: { items: UsageItem[]; groupBy: UsageGroupBy }) {
  const maxCost = Math.max(...items.map((it) => it.cost_usd), 0.000001);
  const bucketLabel = groupBy === "day" ? copy.usage.bucketDay : copy.usage.bucketModel;
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-surface-raised text-zinc-500">
          <tr>
            <th className="px-2 py-1.5 font-medium">{bucketLabel}</th>
            <th className="px-2 py-1.5 text-right font-medium">{copy.usage.runs}</th>
            <th className="px-2 py-1.5 text-right font-medium">{copy.usage.inputTokens}</th>
            <th className="px-2 py-1.5 text-right font-medium">{copy.usage.outputTokens}</th>
            <th className="px-2 py-1.5 text-right font-medium">{copy.usage.cost}</th>
            <th className="w-28 px-2 py-1.5 font-medium">{copy.usage.costShare}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.bucket} className="border-t border-surface-border">
              <td className="px-2 py-1.5 font-mono text-zinc-300">{it.bucket}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-zinc-300">{it.runs}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-zinc-400">
                {formatTokens(it.input_tokens)}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums text-zinc-400">
                {formatTokens(it.output_tokens)}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums text-zinc-300">
                {formatCost(it.cost_usd)}
              </td>
              <td className="px-2 py-1.5">
                <div className="h-1.5 w-full rounded bg-surface">
                  <div
                    className="h-1.5 rounded bg-accent/70"
                    style={{ width: `${Math.max((it.cost_usd / maxCost) * 100, it.cost_usd > 0 ? 2 : 0)}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

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
  const bucketLabel = groupBy === "day" ? copy.usage.bucketDay : copy.usage.bucketModel;

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
        {items.length > 0 ? (
          <Button
            variant="ghost"
            className="ml-auto"
            onClick={() =>
              downloadCsv(items, bucketLabel, `agentd-usage-${groupBy}-${from}_${to}.csv`)
            }
          >
            ⬇ {copy.usage.exportCsv}
          </Button>
        ) : null}
      </Card>

      {!usageQuery.isPending && !usageQuery.isError && items.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
      ) : items.length === 0 ? (
        <Card className="p-8 text-center text-sm text-zinc-500">{copy.usage.empty}</Card>
      ) : (
        <>
          <Card className="p-4">
            {groupBy === "day" ? (
              <UsageByDayChart items={items} />
            ) : (
              <UsageByModelChart items={items} />
            )}
          </Card>
          <Card className="p-3">
            <div className="pb-2 text-sm font-medium">{copy.usage.detail}</div>
            <UsageDetailTable items={items} groupBy={groupBy} />
          </Card>
        </>
      )}
    </div>
  );
}
