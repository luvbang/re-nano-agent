import { useState } from "react";

import type { ChatItem } from "../projection/runProjection";
import { Badge } from "./ui";

function ToolCard({ item }: { item: Extract<ChatItem, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 rounded border border-line bg-base/60">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
        onClick={() => setOpen(!open)}
      >
        <Badge tone={item.status === "ok" ? "ok" : item.status === "error" ? "bad" : "muted"}>
          {item.status === "running" ? "…" : item.status}
        </Badge>
        <span className="font-mono">{item.name}</span>
        <span className="text-dim">{item.durationMs !== null ? `${item.durationMs}ms` : "执行中"}</span>
        <span className="ml-auto text-dim">{open ? "收起" : "参数"}</span>
      </button>
      {open && <pre className="border-t border-line px-3 py-2 text-xs text-dim">{item.args}</pre>}
    </div>
  );
}

export function ChatView({ items, streaming }: { items: ChatItem[]; streaming: boolean }) {
  return (
    <div className="space-y-2">
      {items.map((item, index) =>
        item.kind === "tool" ? (
          <ToolCard key={`tool-${item.id}-${index}`} item={item} />
        ) : (
          <div
            key={`bubble-${index}`}
            className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
              item.kind === "user"
                ? "ml-auto bg-accent/20 text-ink"
                : "bg-panel text-ink"
            }`}
          >
            {item.text || (streaming && item.kind === "assistant" ? "▍" : "")}
          </div>
        ),
      )}
    </div>
  );
}
