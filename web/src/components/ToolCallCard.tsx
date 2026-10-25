/** 工具调用折叠卡：名称 + 路径/状态/耗时；展开看参数与结果预览（文件工具给文件视图）。 */

import { useState } from "react";
import type { ToolCallView } from "../projection/run-projection";

function filePathOf(args: Record<string, unknown>): string | null {
  const p = args["path"] ?? args["file_path"];
  return typeof p === "string" && p.length > 0 ? p : null;
}

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
  const filePath = filePathOf(tool.args);
  const hasArgs = Object.keys(tool.args).length > 0;
  return (
    <div className="rounded-md border border-surface-border bg-surface/60 text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-mono text-zinc-300">🔧 {tool.name}</span>
        {filePath ? (
          <span className="max-w-[40%] truncate font-mono text-[11px] text-zinc-500">
            📄 {filePath}
          </span>
        ) : null}
        <span className={`shrink-0 ${statusTone}`}>
          {statusText}
          {tool.duration_ms !== null ? ` · ${tool.duration_ms}ms` : ""}
        </span>
        <span className="ml-auto shrink-0 text-zinc-600">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        <div className="border-t border-surface-border">
          {hasArgs ? (
            <div className="px-2.5 pt-2">
              <div className="pb-1 text-[11px] text-zinc-600">参数</div>
              <pre className="max-h-32 overflow-auto font-mono text-[11px] leading-relaxed text-zinc-400">
                {JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          ) : null}
          <div className="px-2.5 pt-2">
            <div className="pb-1 text-[11px] text-zinc-600">结果</div>
            {tool.result ? (
              <pre
                className={`max-h-56 overflow-auto pb-2 font-mono text-[11px] leading-relaxed ${
                  tool.status === "error" ? "text-red-200" : "text-zinc-300"
                }`}
              >
                {tool.result}
              </pre>
            ) : tool.status === "running" ? (
              <div className="pb-2 text-[11px] text-zinc-600">执行中…</div>
            ) : (
              <div className="pb-2 text-[11px] text-zinc-600">（无输出）</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
