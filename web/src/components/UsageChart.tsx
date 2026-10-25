/** Usage 图表（data-terminal 规则）：按天双柱（中性+琥珀单色相）+ 按模型细环 + 表格图例。 */

import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { UsageItem } from "../api/types";
import { copy } from "../lib/copy";
import { formatCost, formatTokens } from "../lib/format";
import { EmptyState } from "./StateViews";

const INK = "#f2f2f3";
const MUT = "#8a8c92";
const GRID = "#222224";
const ACCENT = "#f59e0b";

const TOOLTIP_STYLE = {
  background: "#212023",
  border: "1px solid #222224",
  borderRadius: 6,
  fontSize: 12,
  padding: "4px 10px",
} as const;

/** 单色相透明度阶梯（一个 hue，杜绝彩虹图例） */
const AMBER_STEPS = [
  "#f59e0b",
  "rgba(245,158,11,0.62)",
  "rgba(245,158,11,0.40)",
  "rgba(245,158,11,0.26)",
  "rgba(245,158,11,0.16)",
  "rgba(245,158,11,0.10)",
];

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-mut">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

export function UsageByDayChart({ items }: { items: UsageItem[] }) {
  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;
  return (
    <div>
      <div className="flex items-center gap-5 pb-3">
        <h2 className="text-lg font-semibold text-white">{copy.usage.trendTitle}</h2>
        <span className="flex-1" />
        <LegendDot color={MUT} label={copy.usage.legendInput} />
        <LegendDot color={ACCENT} label={copy.usage.legendOutput} />
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={items} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barGap={2}>
          {/* 网格：仅横向 3-5 条实线；无轴线、无刻度线 */}
          <YAxis
            stroke={MUT}
            fontSize={11}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(v: number) => formatTokens(v)}
          />
          <XAxis
            dataKey="bucket"
            stroke={MUT}
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: GRID }}
            interval={2}
            tickFormatter={(v: string) => v.slice(5)}
          />
          <Tooltip
            cursor={{ fill: "rgba(242,242,243,0.04)" }}
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: MUT }}
            itemStyle={{ color: INK }}
            formatter={(value: number, name: string) => [formatTokens(value), name]}
          />
          <Bar dataKey="input_tokens" name={copy.usage.legendInput} fill={MUT} maxBarSize={22} />
          <Bar
            dataKey="output_tokens"
            name={copy.usage.legendOutput}
            fill={ACCENT}
            maxBarSize={22}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function UsageByModelChart({ items }: { items: UsageItem[] }) {
  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;
  const sorted = [...items].sort((a, b) => b.input_tokens - a.input_tokens);
  const total = sorted.reduce((n, it) => n + it.input_tokens, 0);
  return (
    <div>
      <h2 className="pb-3 text-lg font-semibold text-white">{copy.usage.modelTitle}</h2>
      <div className="flex flex-wrap items-center gap-8">
        <div className="relative h-[190px] w-[190px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={sorted}
                dataKey="input_tokens"
                nameKey="bucket"
                innerRadius={72}
                outerRadius={94}
                paddingAngle={1}
                strokeWidth={0}
                startAngle={90}
                endAngle={-270}
              >
                {sorted.map((entry, i) => (
                  <Cell key={entry.bucket} fill={AMBER_STEPS[i % AMBER_STEPS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: MUT }}
                itemStyle={{ color: INK }}
                formatter={(value: number, name: string, entry: { payload?: UsageItem }) => [
                  `${formatTokens(value)} · ${formatCost(entry.payload?.cost_usd ?? 0)}`,
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="num text-lg text-white">{formatTokens(total)}</span>
            <span className="text-xs text-mut">{copy.usage.inputTokens}</span>
          </div>
        </div>
        {/* 图例即表格：色点 = 环片标记本身，数值右对齐 */}
        <table className="min-w-[280px] flex-1 text-sm">
          <thead>
            <tr className="text-xs text-mut">
              <th className="py-1.5 pr-3 text-left font-normal">{copy.usage.bucketModel}</th>
              <th className="py-1.5 px-3 text-right font-normal">{copy.usage.inputTokens}</th>
              <th className="py-1.5 pl-3 text-right font-normal">{copy.usage.cost}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((it, i) => (
              <tr key={it.bucket} className="border-t border-rule">
                <td className="py-2 pr-3">
                  <span className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: AMBER_STEPS[i % AMBER_STEPS.length] }}
                    />
                    <span className="num truncate text-ink">{it.bucket}</span>
                  </span>
                </td>
                <td className="num py-2 px-3 text-right text-ink">{formatTokens(it.input_tokens)}</td>
                <td className="num py-2 pl-3 text-right text-ink">{formatCost(it.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
