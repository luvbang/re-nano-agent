/** 工具调用折叠卡：名称 + 参数 + 状态/耗时，点击展开参数详情。 */

import { useState } from "react";
import type { ToolCallView } from "../projection/run-projection";

export function ToolCallCard({ tool }: { tool: ToolCallView }) {
  const [open, setOpen] = useState(false);
  const statusTone =
    tool.status === "running"
      ? "text-amber-300"
      : tool.status === "ok"
        ? "text-emerald-300"
        : "text-red-300";
  const statusText =
    tool.status === "running" ? "运行中…" : tool.status === "ok" ? "成功" : "失败";
  return (
    <div className="rounded-md border border-surface-border bg-surface/60 text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-mono text-zinc-300">🔧 {tool.name}</span>
        <span className={statusTone}>
          {statusText}
          {tool.duration_ms !== null ? ` · ${tool.duration_ms}ms` : ""}
        </span>
        <span className="ml-auto text-zinc-600">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        <pre className="max-h-40 overflow-auto border-t border-surface-border px-2.5 py-2 font-mono text-[11px] leading-relaxed text-zinc-400">
          {JSON.stringify(tool.args, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
