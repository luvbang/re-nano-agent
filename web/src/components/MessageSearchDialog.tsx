/** 会话内消息搜索：按关键字过滤历史消息/工具名，命中后滚动定位并闪烁高亮。 */

import { useEffect, useMemo, useState } from "react";
import type { ChatItem } from "../projection/run-projection";
import { copy } from "../lib/copy";

function snippet(text: string, needle: string, radius = 26): string {
  const i = text.toLowerCase().indexOf(needle.toLowerCase());
  if (i < 0) return text.slice(0, radius * 2);
  const start = Math.max(0, i - radius);
  const end = Math.min(text.length, i + needle.length + radius);
  return `${start > 0 ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`;
}

export function MessageSearchDialog({
  items,
  onClose,
}: {
  items: ChatItem[];
  onClose: () => void;
}) {
  const [q, setQ] = useState("");

  // 只有带 id 的历史消息可定位（本轮流式项尚无服务端 id）
  const results = useMemo(() => {
    const needle = q.trim();
    if (!needle) return [];
    const lower = needle.toLowerCase();
    const hits: { id: string; label: string; preview: string }[] = [];
    for (const item of items) {
      if (!item.id) continue;
      if (item.kind !== "user" && item.kind !== "assistant") continue;
      if (!item.text.toLowerCase().includes(lower)) continue;
      hits.push({
        id: item.id,
        label: item.kind === "user" ? copy.messageSearch.roleUser : copy.messageSearch.roleAssistant,
        preview: snippet(item.text, needle),
      });
    }
    return hits.slice(0, 50);
  }, [items, q]);

  const jump = (id: string) => {
    onClose();
    requestAnimationFrame(() => {
      const el = document.querySelector<HTMLElement>(`[data-msg-id="${CSS.escape(id)}"]`);
      if (!el) return;
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.classList.remove("msg-flash");
      void el.offsetWidth; // 重启动画
      el.classList.add("msg-flash");
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md animate-fade-up overflow-hidden rounded-lg border border-line bg-panel shadow-pop">
        <div className="border-b border-line px-4 py-3">
          <h2 className="mb-2 text-base font-semibold text-white">{copy.messageSearch.title}</h2>
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && results[0]) jump(results[0].id);
            }}
            placeholder={copy.messageSearch.placeholder}
            className="h-9 w-full rounded-lg border border-control bg-ground px-3 text-sm text-ink placeholder:text-mut focus:border-accent focus:outline-none"
          />
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-2">
          {q.trim() ? (
            <p className="px-2 pb-1 pt-1 text-xs text-mut">
              {results.length > 0 ? copy.messageSearch.hits(results.length) : copy.messageSearch.empty}
            </p>
          ) : null}
          {results.length > 0 ? (
            <ul>
              {results.map((hit) => (
                <li key={hit.id}>
                  <button
                    type="button"
                    onClick={() => jump(hit.id)}
                    className="block w-full rounded-md px-3 py-2 text-left transition-colors hover:bg-raised"
                  >
                    <span className="text-xs text-mut">{hit.label}</span>
                    <p className="truncate text-sm text-ink">{hit.preview}</p>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </div>
  );
}
