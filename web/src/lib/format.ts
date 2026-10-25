/** 展示格式化（纯函数，便于 vitest 直测）。 */

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function formatUptime(seconds: number): string {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}时${m}分`;
  if (m > 0) return `${m}分${s % 60}秒`;
  return `${s}秒`;
}

export function truncateMiddle(text: string, max = 32): string {
  if (text.length <= max) return text;
  const half = Math.floor((max - 1) / 2);
  return `${text.slice(0, half)}…${text.slice(-half)}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function daysAgoISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

/** 用量明细 CSV（v0.2-4 看板导出）：UTF-8 直出，含逗号/引号的字段按 RFC 4180 转义。 */
export function usageCsv(
  items: {
    bucket: string;
    runs: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  }[],
  bucketLabel: string,
): string {
  const cell = (v: string | number): string =>
    typeof v === "number" ? String(v) : /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  const rows = [
    [bucketLabel, "runs", "input_tokens", "output_tokens", "cost_usd"],
    ...items.map((it) => [it.bucket, it.runs, it.input_tokens, it.output_tokens, it.cost_usd]),
  ];
  return rows.map((r) => r.map(cell).join(",")).join("\n");
}
