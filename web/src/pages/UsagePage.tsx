/** Usage：按天/按模型聚合图表 + 分隔 KPI 条 + 明细表（占比条）+ CSV 导出（GET /v1/usage）。 */

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
  const head = "py-2 px-3 text-xs font-normal text-mut";
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-panel">
          <tr>
            <th className={`${head} text-left`}>{bucketLabel}</th>
            <th className={`${head} text-right`}>{copy.usage.runs}</th>
            <th className={`${head} text-right`}>{copy.usage.inputTokens}</th>
            <th className={`${head} text-right`}>{copy.usage.outputTokens}</th>
            <th className={`${head} text-right`}>{copy.usage.cost}</th>
            <th className={`${head} w-32 text-right`}>{copy.usage.costShare}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.bucket} className="border-t border-rule">
              <td className="num py-2.5 px-3 text-ink">{it.bucket}</td>
              <td className="num py-2.5 px-3 text-right text-ink">{it.runs}</td>
              <td className="num py-2.5 px-3 text-right text-mut">{formatTokens(it.input_tokens)}</td>
              <td className="num py-2.5 px-3 text-right text-mut">{formatTokens(it.output_tokens)}</td>
              <td className="num py-2.5 px-3 text-right text-ink">{formatCost(it.cost_usd)}</td>
              <td className="py-2.5 pl-3">
                <div className="h-1 w-full rounded-full bg-ground">
                  <div
                    className="h-1 rounded-full bg-accent"
                    style={{
                      width: `${Math.max((it.cost_usd / maxCost) * 100, it.cost_usd > 0 ? 2 : 0)}%`,
                    }}
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

  const tab = (g: UsageGroupBy, label: string) => (
    <button
      key={g}
      type="button"
      onClick={() => setGroupBy(g)}
      className={`relative h-9 px-3 text-sm transition-colors ${
        groupBy === g ? "sel-bottom font-medium text-white" : "text-mut hover:text-ink"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-[1120px] px-5 pb-12 pt-7 sm:px-8">
      {/* 标题行：h1 + 真实动作 */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-white">{copy.usage.title}</h1>
        <span className="flex-1" />
        {items.length > 0 ? (
          <Button
            variant="text"
            onClick={() =>
              downloadCsv(items, bucketLabel, `agentd-usage-${groupBy}-${from}_${to}.csv`)
            }
          >
            {copy.usage.exportCsv}
          </Button>
        ) : null}
      </div>

      {/* 日期范围（页面级）+ 下划线 Tab：选中 = 同一根 1px 琥珀线 */}
      <div className="mt-5 flex flex-wrap items-end gap-4">
        <label className="text-xs text-mut">
          {copy.usage.from}
          <Input
            type="date"
            className="mt-1.5 h-9 w-44"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className="text-xs text-mut">
          {copy.usage.to}
          <Input
            type="date"
            className="mt-1.5 h-9 w-44"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <div className="ml-2 flex border-b border-line">
          {tab("day", copy.usage.byDay)}
          {tab("model", copy.usage.byModel)}
        </div>
        {usageQuery.isFetching ? (
          <span className="pb-2 text-xs text-mut">{copy.state.loading}</span>
        ) : null}
      </div>

      {/* KPI：一个容器按 1px 分隔线切三格，label 在上、数值 20px 等宽 */}
      {!usageQuery.isPending && !usageQuery.isError && items.length > 0 ? (
        <Card className="mt-5 grid grid-cols-1 divide-y divide-rule sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <div className="px-5 py-4">
            <div className="text-xs text-mut">{copy.usage.totalRuns}</div>
            <div className="num mt-1 text-xl text-white">{totalRuns}</div>
          </div>
          <div className="px-5 py-4">
            <div className="text-xs text-mut">{copy.usage.totalTokens}</div>
            <div className="num mt-1 text-xl text-white">{formatTokens(totalTokens)}</div>
          </div>
          <div className="px-5 py-4">
            <div className="text-xs text-mut">{copy.usage.totalCost}</div>
            <div className="num mt-1 text-xl font-semibold text-white">{formatCost(totalCost)}</div>
          </div>
        </Card>
      ) : null}

      <div className="mt-5">
        {usageQuery.isPending ? (
          <LoadingState />
        ) : usageQuery.isError ? (
          <ErrorState message={usageQuery.error.message} onRetry={() => void usageQuery.refetch()} />
        ) : items.length === 0 ? (
          <EmptyFrame />
        ) : (
          <div className="space-y-5">
            <Card className="p-5">
              {groupBy === "day" ? (
                <UsageByDayChart items={items} />
              ) : (
                <UsageByModelChart items={items} />
              )}
            </Card>
            <Card className="px-2 py-3">
              <h2 className="px-3 pb-2 text-lg font-semibold text-white">{copy.usage.detail}</h2>
              <UsageDetailTable items={items} groupBy={groupBy} />
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyFrame() {
  return (
    <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-control text-sm text-mut">
      {copy.usage.empty}
    </div>
  );
}
