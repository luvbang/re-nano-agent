/** Usage 图表：按天柱状（输入/输出 tokens）+ 按模型占比环图（recharts）。 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { UsageItem } from "../api/types";
import { copy } from "../lib/copy";
import { formatTokens } from "../lib/format";
import { EmptyState } from "./StateViews";

const PALETTE = ["#34d399", "#818cf8", "#f59e0b", "#f87171", "#38bdf8", "#c084fc"];

export function UsageByDayChart({ items }: { items: UsageItem[] }) {
  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={items} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid stroke="#262b36" strokeDasharray="3 3" />
        <XAxis dataKey="group" stroke="#71717a" fontSize={11} tickLine={false} />
        <YAxis
          stroke="#71717a"
          fontSize={11}
          tickLine={false}
          tickFormatter={(v: number) => formatTokens(v)}
        />
        <Tooltip
          contentStyle={{
            background: "#171a21",
            border: "1px solid #262b36",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(value: number, name: string) => [formatTokens(value), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="input_tokens" name="输入" fill="#34d399" radius={[3, 3, 0, 0]} />
        <Bar dataKey="output_tokens" name="输出" fill="#818cf8" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function UsageByModelChart({ items }: { items: UsageItem[] }) {
  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;
  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={items}
          dataKey="input_tokens"
          nameKey="group"
          innerRadius={60}
          outerRadius={100}
          paddingAngle={2}
        >
          {items.map((entry, i) => (
            <Cell key={entry.group} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "#171a21",
            border: "1px solid #262b36",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(value: number, name: string) => [formatTokens(value), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
