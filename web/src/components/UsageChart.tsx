/**
 * Usage 图表（data-terminal 规则）：按天双柱（中性+琥珀单色相）+ 按模型细环 + 表格图例。
 *
 * 手写 SVG，不引第三方图表库（ADR-008「recharts → 轻量自绘」的落地）：
 * 实测 recharts 占 111.5 kB gzip（改动前整包 252.69 kB 的 44%），是超
 * docs/web-architecture.md 体积预算的主因。只保留四个真实能力——双柱、细环、
 * hover tooltip、空态——几何与配色按改动前 recharts 的实际渲染逐项对齐
 * （Y 轴 5 档 nice tick、barCategoryGap 10%/barGap 2/maxBarSize 22、hover 整列
 * 底色 0.04、环片 paddingAngle 1°、tooltip 令牌一致），视觉不变。
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

/** 浮层：与改动前 recharts 默认 tooltip 同一套令牌（raised 底 / 结构线 / 6px 圆角 / 12px 字） */
function ChartTooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 whitespace-nowrap"
      style={{
        left: x,
        top: y,
        transform: "translate(-50%, -100%)",
        padding: "4px 10px",
        background: "#212023",
        border: "1px solid #222224",
        borderRadius: 6,
        fontSize: 12,
        lineHeight: 1.5,
      }}
    >
      {children}
    </div>
  );
}

/** tooltip 的一行："名称 : 值"，名称与数值同为 ink 色（等价 recharts 默认 item 渲染） */
function TooltipItem({ name, value }: { name: string; value: string }) {
  return (
    <div className="num" style={{ color: "#f2f2f3", padding: "4px 0" }}>
      {name} : {value}
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

// 与改动前 ResponsiveContainer height=260 / margin.top=4 / YAxis width=44 一一对应
const SVG_H = 260;
const MARGIN_TOP = 4;
const PLOT_H = 226;
const AXIS_Y = MARGIN_TOP + PLOT_H; // 230：X 轴基线
const Y_W = 44;
const MAX_BAR_W = 22; // 等价 bar maxBarSize
const BAR_GAP = 2; // 等价 barGap={2}
const BAR_CATEGORY_GAP = 0.1; // 等价 barCategoryGap 默认 "10%"
const TICK_COUNT = 5; // 等价 YAxis 默认 tickCount

/** 10 的位数：绝对值落在 [10^n, 10^(n+1)) 时为 n+1（与 recharts-scale 同定义） */
function digitCount(value: number): number {
  return value === 0 ? 1 : Math.floor(Math.log10(Math.abs(value))) + 1;
}

/** 好读的步长：1/2/2.5/5… 级（recharts-scale getFormatStep 的等价实现，整数域） */
function formatStep(rough: number, correction: number): number {
  if (!(rough > 0)) return 0;
  const digits = digitCount(rough);
  const magnitude = 10 ** digits;
  const ratio = rough / magnitude;
  const ratioScale = digits !== 1 ? 0.05 : 0.1;
  const amend = (Math.ceil(ratio / ratioScale) + correction) * ratioScale;
  return Math.ceil(amend * magnitude);
}

/** 保证 tick 数量的刻度区间（recharts-scale calculateStep 的等价实现） */
function tickRange(
  min: number,
  max: number,
  count: number,
  correction = 0,
): { step: number; tickMin: number; tickMax: number } {
  if (!Number.isFinite((max - min) / (count - 1))) return { step: 0, tickMin: 0, tickMax: 0 };
  const step = formatStep((max - min) / (count - 1), correction);
  // 0 在区间内时 0 必是刻度
  let middle = min <= 0 && max >= 0 ? 0 : (min + max) / 2 - (((min + max) / 2) % step || 0);
  let below = step ? Math.ceil((middle - min) / step) : 0;
  let up = step ? Math.ceil((max - middle) / step) : 0;
  const covered = below + up + 1;
  if (covered > count) return tickRange(min, max, count, correction + 1);
  if (covered < count) {
    if (max > 0) up += count - covered;
    else below += count - covered;
  }
  return { step, tickMin: middle - below * step, tickMax: middle + up * step };
}

/** Y 轴刻度值：0 起、5 档 nice tick，末档即坐标轴上界（等价改动前的 recharts 输出） */
function niceTicks(max: number): number[] {
  if (!(max > 0)) return [0];
  const { step, tickMin, tickMax } = tickRange(0, max, TICK_COUNT);
  if (!(step > 0)) return [0, tickMax];
  const out: number[] = [];
  for (let v = tickMin; v < tickMax + step * 0.1 && out.length < 64; v += step) {
    out.push(Number(v.toFixed(6)));
  }
  return out;
}

export function UsageByDayChart({ items }: { items: UsageItem[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [wrapRef, width] = useElementWidth<HTMLDivElement>();

  if (items.length === 0) return <EmptyState>{copy.usage.empty}</EmptyState>;

  const n = items.length;
  const peak = items.reduce((m, it) => Math.max(m, it.input_tokens, it.output_tokens), 0);
  const ticks = niceTicks(peak);
  const top = ticks[ticks.length - 1] || 1;
  const yFor = (v: number) => AXIS_Y - (v / top) * PLOT_H;

  // 柱位（recharts getBarPosition 的等价实现）：band 内留 10% 两侧，
  // 两根柱之间 2px，单柱宽取整后不超过 22px——与改动前的柱宽/间距一致。
  const band = width / n;
  const offset = BAR_CATEGORY_GAP * band;
  const rawSize = (band - 2 * offset - BAR_GAP) / 2;
  const originalSize = rawSize > 1 ? Math.floor(rawSize) : rawSize;
  const barW = Math.min(originalSize, MAX_BAR_W);
  const pairStart = offset + (originalSize - barW) / 2; // 两根柱作为一组居中的起点
  const hovered = hover === null ? null : (items[hover] ?? null);
  const hoverX = hover === null ? 0 : hover * band + band / 2;

  return (
    <div>
      <div className="flex items-center gap-5 pb-3">
        <h2 className="text-lg font-semibold text-white">{copy.usage.trendTitle}</h2>
        <span className="flex-1" />
        <LegendDot color={MUT} label={copy.usage.legendInput} />
        <LegendDot color={ACCENT} label={copy.usage.legendOutput} />
      </div>
      <div className="flex">
        {/* Y 轴刻度：HTML 绘制，11px 字不随容器缩放变形（改动前是 SVG <text>） */}
        <div className="relative shrink-0" style={{ width: Y_W, height: SVG_H }} aria-hidden>
          {ticks.map((t) => (
            <span
              key={t}
              className="num absolute right-2 -translate-y-1/2 whitespace-nowrap text-2xs text-mut"
              style={{ top: yFor(t) }}
            >
              {formatTokens(t)}
            </span>
          ))}
        </div>

        <div className="relative min-w-0 flex-1" ref={wrapRef}>
          <svg
            width={Math.max(width, 1)}
            height={SVG_H}
            viewBox={`0 0 ${Math.max(width, 1)} ${SVG_H}`}
            role="img"
            aria-label={copy.usage.trendTitle}
            className="block"
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${copy.usage.trendTitle}：${copy.usage.legendInput} / ${copy.usage.legendOutput}`}</title>
            {/* 轴向结构：只有一条 X 轴基线（改动前同样没有横向网格线、无刻度线） */}
            <line
              x1={0}
              x2={Math.max(width, 1)}
              y1={AXIS_Y}
              y2={AXIS_Y}
              stroke={GRID}
              strokeWidth={1}
              shapeRendering="crispEdges"
            />
            {width > 0
              ? items.map((it, i) => {
                  const x = i * band;
                  return (
                    <g key={it.bucket} onMouseEnter={() => setHover(i)}>
                      {/* 命中区：整条 band 都算 hover（等价 recharts 的 cursor 底色），移动端也够大 */}
                      <rect
                        x={x}
                        y={MARGIN_TOP}
                        width={band}
                        height={PLOT_H}
                        fill={hover === i ? "rgba(242,242,243,0.04)" : "transparent"}
                      />
                      <rect
                        x={x + pairStart}
                        y={yFor(it.input_tokens)}
                        width={Math.max(barW, 0.5)}
                        height={Math.max(AXIS_Y - yFor(it.input_tokens), 0)}
                        fill={MUT}
                      />
                      <rect
                        x={x + pairStart + originalSize + BAR_GAP}
                        y={yFor(it.output_tokens)}
                        width={Math.max(barW, 0.5)}
                        height={Math.max(AXIS_Y - yFor(it.output_tokens), 0)}
                        fill={ACCENT}
                      />
                    </g>
                  );
                })
              : null}
          </svg>

          {/* X 轴标签：每 3 个取 1（等价改动前 interval={2}） */}
          <div className="relative" style={{ height: SVG_H - AXIS_Y }} aria-hidden>
            {items.map((it, i) =>
              i % 3 === 0 ? (
                <span
                  key={it.bucket}
                  className="num absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap text-2xs text-mut"
                  style={{ left: (i + 0.5) * band, top: 8 }}
                >
                  {it.bucket.slice(5)}
                </span>
              ) : null,
            )}
          </div>

          {hovered && hover !== null && width > 0 ? (
            <ChartTooltip
              x={Math.min(Math.max(hoverX, 56), Math.max(width - 56, 56))}
              y={Math.max(Math.min(yFor(Math.max(hovered.input_tokens, hovered.output_tokens)), AXIS_Y) - 6, 60)}
            >
              <div className="num" style={{ color: MUT }}>
                {hovered.bucket}
              </div>
              <TooltipItem name={copy.usage.legendInput} value={formatTokens(hovered.input_tokens)} />
              <TooltipItem name={copy.usage.legendOutput} value={formatTokens(hovered.output_tokens)} />
            </ChartTooltip>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── 按模型细环 ───────────────────────── */

const RING = 190; // 画布尺寸，与改动前的 190×190 一致
const R_OUT = 94; // 环片外半径（等价 outerRadius）
const R_IN = 72; // 内半径（等价 innerRadius，中心留白放总量）
const PAD_DEG = 1; // 片间缝（等价 paddingAngle=1）

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
  // 角度分配（等价 recharts Pie 的 paddingAngle 语义）：先从整圆里扣掉每片的 1° 缝，
  // 再按占比分剩下的角度——否则末尾会攒出一大块空白缺口。
  const nonZero = sorted.filter((it) => it.input_tokens !== 0).length;
  const realTotal = 360 - nonZero * PAD_DEG;
  let cursor = 0;
  const slices = sorted.map((it, i) => {
    const share = total > 0 ? it.input_tokens / total : 0;
    const from = i === 0 ? 0 : cursor + (it.input_tokens !== 0 ? PAD_DEG : 0);
    const to = from + (it.input_tokens !== 0 ? share * realTotal : 0);
    cursor = to;
    return { it, i, from, to, mid: (from + to) / 2 };
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
              <TooltipItem
                name={hovered.bucket}
                value={`${formatTokens(hovered.input_tokens)} · ${formatCost(hovered.cost_usd)}`}
              />
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
