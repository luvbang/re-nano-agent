/**
 * Usage 图表（data-terminal 规则）：按天双柱（中性+琥珀单色相）+ 按模型细环 + 表格图例。
 *
 * 手写 SVG，不引第三方图表库（ADR-008「recharts → 轻量自绘」的落地）：
 * 实测 recharts 占 111.5 kB gzip（占改动前整包 252.7 kB 的 44%），是超
 * docs/web-architecture.md 体积预算的主因。这里只保留四个真实能力——
 * 双柱、细环、hover tooltip、空态——尺寸/配色/空态沿用改动前的视觉。
 * 带 <title> 让图表对读屏器有可访问名（recharts 默认不输出）。
 */

import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { UsageItem } from "../api/types";
import { copy } from "../lib/copy";
import { formatCost, formatTokens } from "../lib/format";
import { EmptyState } from "./StateViews";

const MUT = "#8a8c92";
const GRID = "#222224";
const ACCENT = "#f59e0b";

/** 单色相透明度阶梯（一个 hue，杜绝彩虹图例） */
const AMBER_STEPS = [
  "#f59e0b",
  "rgba(245,158,11,0.62)",
  "rgba(245,158,11,0.40)",
  "rgba(245,158,11,0.26)",
  "rgba(245,158,11,0.16)",
  "rgba(245,158,11,0.10)",
];

const stepColor = (i: number): string => AMBER_STEPS[i % AMBER_STEPS.length] ?? AMBER_STEPS[0]!;

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-mut">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

/** 浮层：比面板亮一档的底色 + 1px 结构线，与改动前的 tooltip 同一套色 */
function ChartTooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 whitespace-nowrap rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs shadow-pop"
      style={{ left: x, top: y, transform: "translate(-50%, -100%)" }}
    >
      {children}
    </div>
  );
}

/** 容器实测宽度：手写图表按像素布局，柱宽/间距不用百分号缩放（否则 1 天数据会变胖柱） */
function useElementWidth<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/* ───────────────────────── 按天双柱 ───────────────────────── */

const PLOT_H = 240; // 绘图区高度（等价改动前 ResponsiveContainer height=260 去掉轴行）
const AXIS_H = 18; // X 轴标签行
const Y_W = 44; // 左侧刻度槽（等价改动前 YAxis width=44）
const MAX_BAR_W = 22; // 等价改动前 maxBarSize
const BAR_GAP = 2; // 等价改动前 barGap

/** 3-5 条"整数级"横向网格线：1/2/2.5/5×10^n 步进（自绘版自动刻度） */
function niceTicks(max: number): number[] {
  if (!(max > 0)) return [0];
  const rough = max / 4;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const count = Math.max(1, Math.ceil(max / step));
  return Array.from({ length: count + 1 }, (_, i) => i * step);
}

export function UsageByDayChart({ items }: { items: UsageItem[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [wrapRef, width] = useElementWidth<HTMLDivElement>();

  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;

  const n = items.length;
  const peak = items.reduce((m, it) => Math.max(m, it.input_tokens, it.output_tokens), 0);
  const ticks = niceTicks(peak);
  const top = ticks[ticks.length - 1] || 1;
  const slot = width / n;
  const barW = Math.max(Math.min(slot * 0.34, MAX_BAR_W), 1);
  const gap = Math.min(slot * 0.1, BAR_GAP);
  const yFor = (v: number) => PLOT_H - (v / top) * PLOT_H;
  const hovered = hover === null ? null : (items[hover] ?? null);
  const hoverX = hover === null ? 0 : (hover + 0.5) * slot;

  return (
    <div>
      <div className="flex items-center gap-5 pb-3">
        <h2 className="text-lg font-semibold text-white">{copy.usage.trendTitle}</h2>
        <span className="flex-1" />
        <LegendDot color={MUT} label={copy.usage.legendInput} />
        <LegendDot color={ACCENT} label={copy.usage.legendOutput} />
      </div>
      <div className="flex">
        {/* Y 轴刻度：HTML 绘制，11px 字不随容器缩放变形 */}
        <div className="relative shrink-0" style={{ width: Y_W, height: PLOT_H }} aria-hidden>
          {ticks.map((t) => (
            <span
              key={t}
              className="num absolute right-2 -translate-y-1/2 text-2xs text-mut"
              style={{ top: yFor(t) }}
            >
              {formatTokens(t)}
            </span>
          ))}
        </div>

        <div className="relative min-w-0 flex-1" ref={wrapRef}>
          <svg
            width={Math.max(width, 1)}
            height={PLOT_H + AXIS_H}
            viewBox={`0 0 ${Math.max(width, 1)} ${PLOT_H + AXIS_H}`}
            role="img"
            aria-label={copy.usage.trendTitle}
            className="block"
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${copy.usage.trendTitle}：${copy.usage.legendInput} / ${copy.usage.legendOutput}`}</title>
            {/* 网格：仅横向实线；无轴线（只留基线）、无刻度线 */}
            {ticks.map((t) => (
              <line
                key={t}
                x1={0}
                x2={width}
                y1={yFor(t)}
                y2={yFor(t)}
                stroke={GRID}
                strokeWidth={1}
                shapeRendering="crispEdges"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {width > 0
              ? items.map((it, i) => (
                  <g key={it.bucket} onMouseEnter={() => setHover(i)}>
                    {/* 命中区：整条 slot 都算 hover（移动端也够大），等价 recharts 的 cursor 底色 */}
                    <rect
                      x={i * slot}
                      y={0}
                      width={slot}
                      height={PLOT_H}
                      fill={hover === i ? "rgba(242,242,243,0.04)" : "transparent"}
                    />
                    <rect
                      x={i * slot + slot / 2 - gap - barW}
                      y={yFor(it.input_tokens)}
                      width={barW}
                      height={Math.max(PLOT_H - yFor(it.input_tokens), 0)}
                      fill={MUT}
                    />
                    <rect
                      x={i * slot + slot / 2 + gap}
                      y={yFor(it.output_tokens)}
                      width={barW}
                      height={Math.max(PLOT_H - yFor(it.output_tokens), 0)}
                      fill={ACCENT}
                    />
                  </g>
                ))
              : null}
          </svg>

          {/* X 轴标签：每 3 个取 1（等价改动前 interval={2}），末位始终显示 */}
          <div className="relative" style={{ height: AXIS_H }} aria-hidden>
            {items.map((it, i) =>
              i % 3 === 0 || i === n - 1 ? (
                <span
                  key={it.bucket}
                  className="num absolute -translate-x-1/2 whitespace-nowrap text-2xs text-mut"
                  style={{ left: (i + 0.5) * slot }}
                >
                  {it.bucket.slice(5)}
                </span>
              ) : null,
            )}
          </div>

          {hovered && hover !== null && width > 0 ? (
            <ChartTooltip
              x={Math.min(Math.max(hoverX, 56), Math.max(width - 56, 56))}
              // 夹在绘图区内：柱子很高时浮层压在柱子上（与改动前 recharts 的跟随行为一致），
              // 但不会窜出图表去盖住标题/图例。
              y={Math.max(
                Math.min(yFor(Math.max(hovered.input_tokens, hovered.output_tokens)), PLOT_H) - 6,
                60,
              )}
            >
              <div className="num pb-1 text-mut">{hovered.bucket}</div>
              <div className="num flex items-center gap-1.5 text-ink">
                <span className="h-2 w-2 rounded-full" style={{ background: MUT }} />
                {copy.usage.legendInput} {formatTokens(hovered.input_tokens)}
              </div>
              <div className="num flex items-center gap-1.5 text-ink">
                <span className="h-2 w-2 rounded-full" style={{ background: ACCENT }} />
                {copy.usage.legendOutput} {formatTokens(hovered.output_tokens)}
              </div>
            </ChartTooltip>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── 按模型细环 ───────────────────────── */

const RING = 190; // 画布尺寸，与改动前的 190×190 一致
const R_OUT = 94; // 环片外半径（等价改动前 outerRadius）
const R_IN = 72; // 内半径（等价改动前 innerRadius，中心留白放总量）
const PAD_DEG = 1; // 片间缝（等价改动前 paddingAngle=1）

/** 极坐标取点：0° 指向 12 点，顺时针 */
function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** 环形扇区路径：外弧顺时针 → 内弧回卷；整圆时把 sweep 收在 359.999° 防 arc 退化 */
function ringPath(cx: number, cy: number, from: number, to: number) {
  const sweep = Math.min(Math.max(to - from, 0), 359.999);
  const a = polar(cx, cy, R_OUT, from);
  const b = polar(cx, cy, R_OUT, from + sweep);
  const c = polar(cx, cy, R_IN, from + sweep);
  const d = polar(cx, cy, R_IN, from);
  const large = sweep > 180 ? 1 : 0;
  const p = (v: number) => v.toFixed(3);
  return [
    `M ${p(a.x)} ${p(a.y)}`,
    `A ${R_OUT} ${R_OUT} 0 ${large} 1 ${p(b.x)} ${p(b.y)}`,
    `L ${p(c.x)} ${p(c.y)}`,
    `A ${R_IN} ${R_IN} 0 ${large} 0 ${p(d.x)} ${p(d.y)}`,
    "Z",
  ].join(" ");
}

export function UsageByModelChart({ items }: { items: UsageItem[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;

  const sorted = [...items].sort((a, b) => b.input_tokens - a.input_tokens);
  const total = sorted.reduce((n, it) => n + it.input_tokens, 0);
  const cx = RING / 2;
  const cy = RING / 2;
  let cursor = 0;
  const slices = sorted.map((it, i) => {
    const share = total > 0 ? it.input_tokens / total : 0;
    const from = cursor;
    cursor += share * 360;
    return { it, i, from, to: Math.max(from + share * 360 - PAD_DEG, from), mid: from + share * 180 };
  });
  const hovered = hover === null ? null : (sorted[hover] ?? null);
  const hoveredSlice = hover === null ? null : (slices[hover] ?? null);
  const tip = hoveredSlice
    ? polar(cx, cy, (R_OUT + R_IN) / 2, hoveredSlice.mid)
    : { x: cx, y: cy };

  return (
    <div>
      <h2 className="pb-3 text-lg font-semibold text-white">{copy.usage.modelTitle}</h2>
      <div className="flex flex-wrap items-center gap-8">
        <div className="relative h-[190px] w-[190px] shrink-0">
          <svg
            width={RING}
            height={RING}
            viewBox={`0 0 ${RING} ${RING}`}
            role="img"
            aria-label={copy.usage.modelTitle}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${copy.usage.modelTitle}：${copy.usage.inputTokens}`}</title>
            {total > 0 ? (
              slices.map((s) => (
                <path
                  key={s.it.bucket}
                  d={ringPath(cx, cy, s.from, s.to)}
                  fill={stepColor(s.i)}
                  onMouseEnter={() => setHover(s.i)}
                />
              ))
            ) : (
              // 全为 0 时退化成一条静默底环，仍保留图表锚点（不变成空白块）
              <circle
                cx={cx}
                cy={cy}
                r={(R_OUT + R_IN) / 2}
                fill="none"
                stroke={GRID}
                strokeWidth={R_OUT - R_IN}
              />
            )}
          </svg>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="num text-lg text-white">{formatTokens(total)}</span>
            <span className="text-xs text-mut">{copy.usage.inputTokens}</span>
          </div>
          {hovered ? (
            <ChartTooltip x={tip.x} y={tip.y}>
              <div className="num pb-1 text-mut">{hovered.bucket}</div>
              <div className="num text-ink">
                {formatTokens(hovered.input_tokens)} · {formatCost(hovered.cost_usd)}
              </div>
            </ChartTooltip>
          ) : null}
        </div>
        {/* 图例即表格：色点 = 环片标记本身，数值右对齐；行 hover 与环片联动 */}
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
              <tr
                key={it.bucket}
                className={`border-t border-rule ${hover === i ? "bg-raised" : ""}`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <td className="py-2 pr-3">
                  <span className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: stepColor(i) }}
                    />
                    <span className="num truncate text-ink">{it.bucket}</span>
                  </span>
                </td>
                <td className="num py-2 px-3 text-right text-ink">
                  {formatTokens(it.input_tokens)}
                </td>
                <td className="num py-2 pl-3 text-right text-ink">{formatCost(it.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
