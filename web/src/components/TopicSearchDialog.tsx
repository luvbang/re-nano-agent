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
      <div className="w-full max-w-md animate-fade-up overflow-hidden rounded-lg border border-line bg-panel shadow-pop">
        <div className="border-b border-line px-4 py-3">
          <h2 className="mb-2 text-base font-semibold text-white">{copy.topicSearch.title}</h2>
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && results[0]) jump(results[0].id);
            }}
            placeholder={copy.topicSearch.placeholder}
            className="h-9 w-full rounded-lg border border-control bg-ground px-3 text-sm text-ink placeholder:text-mut focus:border-accent focus:outline-none"
          />
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-2">
          <p className="px-2 pb-1 pt-1 text-xs text-mut">
            {q.trim() ? copy.topicSearch.hits(results.length) : copy.sidebar.topics}
          </p>
          {results.length === 0 ? (
            <p className="px-2 py-4 text-center text-sm text-mut">{copy.topicSearch.empty}</p>
          ) : (
            <ul>
              {results.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => jump(s.id)}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition-colors hover:bg-raised"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">
                      {s.title || copy.sidebar.untitled}
                    </span>
                    {s.id === currentId ? (
                      <span className="rounded bg-accent/10 px-1.5 py-0.5 text-xs text-accent">
                        {copy.topicSearch.current}
                      </span>
                    ) : null}
                    <span className="num shrink-0 text-xs text-mut">{day(s.updated_at)}</span>
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
