/** 话题搜索弹窗：标题关键字过滤，回车/点击跳转到该会话。Esc 或遮罩点击关闭。 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import type { SessionInfo } from "../api/types";
import { copy } from "../lib/copy";

function day(iso: string): string {
  return iso.slice(0, 10);
}

export function TopicSearchDialog({
  sessions,
  currentId,
  onClose,
}: {
  sessions: SessionInfo[];
  currentId: string | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle
      ? sessions.filter((s) => (s.title ?? "").toLowerCase().includes(needle))
      : sessions;
    return list.slice(0, 30);
  }, [sessions, q]);

  const jump = (id: string) => {
    onClose();
    navigate(`/playground?session=${id}`);
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
      <div className="w-full max-w-md animate-fade-up overflow-hidden rounded-xl border border-surface-border bg-surface-raised shadow-pop">
        <div className="border-b border-surface-border px-4 py-3">
          <h2 className="mb-2 text-sm font-semibold text-zinc-100">{copy.topicSearch.title}</h2>
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && results[0]) jump(results[0].id);
            }}
            placeholder={copy.topicSearch.placeholder}
            className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-accent focus:outline-none"
          />
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-2">
          <p className="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
            {q.trim() ? copy.topicSearch.hits(results.length) : copy.sidebar.topics}
          </p>
          {results.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-zinc-600">{copy.topicSearch.empty}</p>
          ) : (
            <ul>
              {results.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => jump(s.id)}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-surface"
                  >
                    <span className="min-w-0 flex-1 truncate text-xs text-zinc-200">
                      {s.title || copy.sidebar.untitled}
                    </span>
                    {s.id === currentId ? (
                      <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-amber-300">
                        {copy.topicSearch.current}
                      </span>
                    ) : null}
                    <span className="shrink-0 text-[10px] tabular-nums text-zinc-600">
                      {day(s.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
