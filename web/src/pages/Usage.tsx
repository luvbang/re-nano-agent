import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { UsageItem, UsageResponse } from "../api/types";
import { Card, Empty, ErrorBox, Input, PageTitle, Spinner } from "../components/ui";
import { useKeys } from "../hooks/keys";

function Bars({ items }: { items: UsageItem[] }) {
  const max = Math.max(...items.map((item) => item.input_tokens + item.output_tokens), 1);
  return (
    <div className="space-y-2">
      {items.map((item) => {
        return (
          <div key={item.bucket} className="text-xs">
            <div className="mb-1 flex justify-between text-dim">
              <span>{item.bucket}</span>
              <span>
                {item.runs} runs · in {item.input_tokens} / out {item.output_tokens} · $
                {item.cost_usd.toFixed(4)}
              </span>
            </div>
            <div className="flex h-3 overflow-hidden rounded bg-base">
              <div
                className="bg-accent"
                style={{ width: `${(item.input_tokens / max) * 100}%` }}
                title="input"
              />
              <div
                className="bg-accent/40"
                style={{ width: `${(item.output_tokens / max) * 100}%` }}
                title="output"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Usage() {
  const { projectKey } = useKeys();
  const [groupBy, setGroupBy] = useState<"day" | "model">("day");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = new URLSearchParams({ group_by: groupBy });
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const query = useQuery({
    queryKey: ["usage", groupBy, dateFrom, dateTo],
    queryFn: () => api<UsageResponse>(`/v1/usage?${params}`, projectKey),
    enabled: Boolean(projectKey),
  });

  if (!projectKey) return <Empty>需要项目 key。</Empty>;
  return (
    <div>
      <PageTitle>Usage</PageTitle>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <div className="flex rounded border border-line">
          {(["day", "model"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={`px-3 py-1.5 text-xs ${groupBy === mode ? "bg-line/40 text-ink" : "text-dim"}`}
              onClick={() => setGroupBy(mode)}
            >
              按{mode === "day" ? "天" : "模型"}
            </button>
          ))}
        </div>
        <Input
          type="date"
          className="!w-40"
          value={dateFrom}
          onChange={(event) => setDateFrom(event.target.value)}
        />
        <span className="text-dim">→</span>
        <Input
          type="date"
          className="!w-40"
          value={dateTo}
          onChange={(event) => setDateTo(event.target.value)}
        />
      </div>
      {query.isLoading ? (
        <Spinner />
      ) : query.error ? (
        <ErrorBox>{String(query.error)}</ErrorBox>
      ) : !query.data || query.data.items.length === 0 ? (
        <Empty>该区间还没有用量记录。</Empty>
      ) : (
        <Card>
          <Bars items={query.data.items} />
        </Card>
      )}
    </div>
  );
}
