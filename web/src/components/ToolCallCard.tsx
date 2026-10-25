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
      ? "text-warn"
      : tool.status === "ok"
        ? "text-pos"
        : "text-neg";
  const statusText =
    tool.status === "running" ? "运行中…" : tool.status === "ok" ? "成功" : "失败";
  const filePath = filePathOf(tool.args);
  const hasArgs = Object.keys(tool.args).length > 0;
  return (
    <div className="rounded-md border border-line bg-panel text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="num text-ink">{tool.name}</span>
        {filePath ? (
          <span className="num max-w-[40%] truncate text-mut">{filePath}</span>
        ) : null}
        <span className={`shrink-0 ${statusTone}`}>
          {statusText}
          {tool.duration_ms !== null ? <span className="num"> · {tool.duration_ms}ms</span> : ""}
        </span>
        <span className="ml-auto shrink-0 text-mut">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        <div className="border-t border-line">
          {hasArgs ? (
            <div className="px-2.5 pt-2">
              <div className="pb-1 text-xs text-mut">参数</div>
              <pre className="num max-h-32 overflow-auto rounded-md bg-ground p-2 text-xs leading-relaxed text-mut">
                {JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          ) : null}
          <div className="px-2.5 pt-2">
            <div className="pb-1 text-xs text-mut">结果</div>
            {tool.result ? (
              <pre
                className={`num max-h-56 overflow-auto rounded-md bg-ground p-2 pb-2 text-xs leading-relaxed ${
                  tool.status === "error" ? "text-neg" : "text-ink"
                }`}
              >
                {tool.result}
              </pre>
            ) : tool.status === "running" ? (
              <div className="pb-2 text-xs text-mut">执行中…</div>
            ) : (
              <div className="pb-2 text-xs text-mut">（无输出）</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
