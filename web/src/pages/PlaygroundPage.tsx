/**
 * Playground：选/建 session → 发消息 → SSE 流式渲染（§1 范围的唯一工作台）。
 * 会话历史来自 GET messages（续聊），本轮流式状态来自 useRunStream 投影。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { useRunStream } from "../hooks/useRunStream";
import { historyToItems, type ChatItem } from "../projection/run-projection";
import { ChatMessageView } from "../components/ChatMessage";
import { EmptyState } from "../components/StateViews";
import { Badge, Button } from "../components/ui";
import { copy } from "../lib/copy";
import { truncateMiddle } from "../lib/format";

export function PlaygroundPage() {
  const { client, mode } = useAdminKey();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSession = searchParams.get("session");
  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["sessions", mode],
    queryFn: () => client.listSessions(50),
  });

  const historyQuery = useQuery({
    queryKey: ["messages", mode, sessionId],
    queryFn: () => client.listMessages(sessionId!, { limit: 100 }),
    enabled: sessionId !== null,
  });

  const { projection, sending, send, cancel, reset } = useRunStream(client, sessionId);

  // run 成功后：服务端已落库 → 刷新历史、以服务端真相渲染，再清空本轮流式投影
  // （避免“下一轮发送时上一轮从视图消失”或历史+投影双重渲染）
  useEffect(() => {
    if (projection.phase !== "completed" || sessionId === null) return;
    let cancelled = false;
    void (async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages", mode, sessionId] });
      if (!cancelled) reset();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projection.phase, sessionId]);

  // 无会话时自动选最近一个（URL 带 session 参数时优先）
  useEffect(() => {
    if (urlSession) {
      setSessionId(urlSession);
      return;
    }
    if (sessionId === null && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setSessionId(sessionsQuery.data[0]!.id);
    }
  }, [urlSession, sessionId, sessionsQuery.data]);

  const historyItems = useMemo(() => historyToItems(historyQuery.data ?? []), [historyQuery.data]);

  const items: ChatItem[] = useMemo(() => {
    if (projection.phase === "idle") return historyItems;
    // 本轮交换（用户消息 + 流式回答）替换历史尾部视图；失败轮不落历史
    if (projection.phase === "failed" && projection.items.length === 0) return historyItems;
    return [...historyItems, ...projection.items];
  }, [historyItems, projection]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items.length, projection.lastSeq]);

  const newSession = useCallback(async () => {
    const s = await client.createSession({ title: `会话 ${new Date().toLocaleString("zh-CN")}` });
    reset();
    setSessionId(s.id);
    await queryClient.invalidateQueries({ queryKey: ["sessions", mode] });
  }, [client, reset, queryClient, mode]);

  const submit = () => {
    const text = draft.trim();
    if (!text || sending || !sessionId) return;
    setDraft("");
    void send(text);
  };

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col p-4">
      <div className="flex items-center gap-3 pb-3">
        <span className="text-sm text-zinc-400">{copy.playground.sessionLabel}</span>
        <select
          className="max-w-xs flex-1 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-sm text-zinc-200"
          value={sessionId ?? ""}
          onChange={(e) => {
            reset();
            const next = e.target.value || null;
            setSessionId(next);
            if (next) {
              setSearchParams({ session: next }, { replace: true });
            } else {
              setSearchParams({}, { replace: true });
            }
          }}
        >
          {(sessionsQuery.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {truncateMiddle(s.title ?? s.id, 24)}
            </option>
          ))}
        </select>
        <Button variant="ghost" onClick={() => void newSession()}>
          {copy.playground.newSession}
        </Button>
        {sending ? (
          <Button variant="danger" onClick={() => void cancel()}>
            {copy.playground.stop}
          </Button>
        ) : null}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-lg border border-surface-border bg-surface/40 p-4">
        {items.length === 0 ? (
          <EmptyState>{copy.playground.emptyHistory}</EmptyState>
        ) : (
          items.map((item, i) => <ChatMessageView key={i} item={item} />)
        )}
        {projection.phase === "failed" && projection.error ? (
          <div className="rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {copy.playground.failedBar(projection.error.code, projection.error.message)}
          </div>
        ) : null}
        {projection.usage && projection.phase === "completed" ? (
          <div className="text-right">
            <Badge tone="success">
              {copy.playground.usageBar(
                projection.usage.input_tokens,
                projection.usage.output_tokens,
              )}
            </Badge>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <div className="pt-3">
        <textarea
          className="w-full resize-none rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-accent focus:outline-none"
          rows={2}
          placeholder={copy.playground.inputPlaceholder}
          value={draft}
          disabled={!sessionId}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="mt-2 flex justify-end">
          <Button onClick={submit} disabled={!draft.trim() || sending || !sessionId}>
            {copy.playground.send}
          </Button>
        </div>
      </div>
    </div>
  );
}
