/**
 * Playground：选/建 session → 发消息 → SSE 流式渲染（§1 范围的唯一工作台）。
 * 会话历史来自 GET messages（续聊），本轮流式状态来自 useRunStream 投影。
 * 绑定项目 key 后，本页全部请求走最小权限的项目 key（其余页面仍用管理员 key）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { useRunStream } from "../hooks/useRunStream";
import { historyToItems, type ChatItem } from "../projection/run-projection";
import { ChatMessageView } from "../components/ChatMessage";
import { EmptyState } from "../components/StateViews";
import { Badge, Button, Spinner } from "../components/ui";
import { copy } from "../lib/copy";
import { truncateMiddle } from "../lib/format";
import type { Usage } from "../api/types";

/** 只有用户本来就在底部附近时才自动跟随滚动（否则会被流式输出强行拽回） */
const PIN_THRESHOLD_PX = 60;

export function PlaygroundPage() {
  const { client, playgroundClient, playgroundKey, setPlaygroundKey, mode } = useAdminKey();
  // Playground 全部请求使用绑定的项目 key（无绑定则回落管理员 key），
  // 保证“会话列表/创建/发消息”都在同一个 project 作用域内
  const pgClient = playgroundClient ?? client;
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSession = searchParams.get("session");
  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [draft, setDraft] = useState("");
  const [pinned, setPinned] = useState(true);
  const [lastUsage, setLastUsage] = useState<Usage | null>(null);
  const lastInputRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["pg-sessions", mode, playgroundKey],
    queryFn: () => pgClient.listSessions(50),
  });

  const historyQuery = useQuery({
    queryKey: ["pg-messages", mode, playgroundKey, sessionId],
    queryFn: () => pgClient.listMessages(sessionId!, { limit: 100 }),
    enabled: sessionId !== null,
  });

  const { projection, sending, send, cancel, reset } = useRunStream(pgClient, sessionId);

  // run 成功后：服务端已落库 → 刷新历史、以服务端真相渲染，再清空本轮流式投影
  // （避免“下一轮发送时上一轮从视图消失”或历史+投影双重渲染）
  useEffect(() => {
    if (projection.phase !== "completed" || sessionId === null) return;
    let cancelled = false;
    void (async () => {
      await queryClient.invalidateQueries({ queryKey: ["pg-messages", mode, playgroundKey, sessionId] });
      if (!cancelled) reset();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projection.phase, sessionId]);

  // 完成后把本轮用量留存在页面上，直到下次发送（避免 invalidate+reset 后徽标闪现即逝）
  useEffect(() => {
    if (projection.phase === "completed" && projection.usage) setLastUsage(projection.usage);
  }, [projection.phase, projection.usage]);

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
    // 本轮交换（用户消息 + 流式回答）替换历史尾部视图；失败/取消轮不落历史
    if (
      (projection.phase === "failed" || projection.phase === "cancelled") &&
      projection.items.length === 0
    ) {
      return historyItems;
    }
    return [...historyItems, ...projection.items];
  }, [historyItems, projection]);

  // sticky-bottom：仅在用户贴近底部时跟随；流式期间用即时滚动避免 smooth 动画堆积
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !pinned) return;
    el.scrollTop = el.scrollHeight;
  }, [items, projection.lastSeq, pinned]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < PIN_THRESHOLD_PX);
  }, []);

  const newSession = useCallback(async () => {
    const s = await pgClient.createSession({ title: `会话 ${new Date().toLocaleString("zh-CN")}` });
    reset();
    setLastUsage(null);
    setSessionId(s.id);
    await queryClient.invalidateQueries({ queryKey: ["pg-sessions", mode, playgroundKey] });
  }, [pgClient, reset, queryClient, mode, playgroundKey]);

  const submit = () => {
    const text = draft.trim();
    if (!text || sending || !sessionId) return;
    setDraft("");
    setLastUsage(null);
    lastInputRef.current = text;
    setPinned(true);
    void send(text);
  };

  const showFailedBar = projection.phase === "failed" && projection.error !== null;
  const showCancelledBar = projection.phase === "cancelled" && projection.items.length > 0;
  const usage = projection.phase === "completed" ? projection.usage : lastUsage;

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col p-4">
      <div className="flex flex-wrap items-center gap-3 pb-3">
        <span className="text-sm text-zinc-400">{copy.playground.sessionLabel}</span>
        <select
          className="max-w-xs flex-1 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-sm text-zinc-200"
          value={sessionId ?? ""}
          onChange={(e) => {
            reset();
            setLastUsage(null);
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
        {playgroundKey ? (
          <Badge tone="warn">
            <span className="flex items-center gap-2">
              {copy.playground.projectKeyBadge(truncateMiddle(playgroundKey, 10))}
              <button
                type="button"
                className="underline underline-offset-2 hover:text-amber-100"
                onClick={() => setPlaygroundKey(null)}
              >
                {copy.playground.useAdminKeyAgain}
              </button>
            </span>
          </Badge>
        ) : null}
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="relative flex-1 space-y-3 overflow-y-auto rounded-lg border border-surface-border bg-surface/40 p-4"
      >
        {items.length === 0 ? (
          <EmptyState>{copy.playground.emptyHistory}</EmptyState>
        ) : (
          items.map((item, i) => (
            <ChatMessageView key={i < historyItems.length ? `h-${i}` : `live-${i}`} item={item} />
          ))
        )}
        {showFailedBar && projection.error ? (
          <div className="flex items-center gap-3 rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            <span className="flex-1">
              {copy.playground.failedBar(projection.error.code, projection.error.message)}
            </span>
            {projection.error.retryable && lastInputRef.current ? (
              <Button variant="ghost" onClick={() => void send(lastInputRef.current!)}>
                {copy.playground.retry}
              </Button>
            ) : null}
          </div>
        ) : null}
        {showCancelledBar ? (
          <div className="rounded-md border border-amber-900 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
            {copy.playground.cancelledBar}
          </div>
        ) : null}
        {usage ? (
          <div className="text-right">
            <Badge tone="success">{copy.playground.usageBar(usage.input_tokens, usage.output_tokens)}</Badge>
          </div>
        ) : null}
        {!pinned ? (
          <button
            type="button"
            onClick={() => {
              setPinned(true);
              const el = scrollRef.current;
              if (el) el.scrollTop = el.scrollHeight;
            }}
            className="sticky bottom-2 ml-auto block rounded-full border border-surface-border bg-surface-raised px-3 py-1 text-xs text-zinc-300 shadow-md hover:text-zinc-100"
          >
            ↓ {copy.playground.send}
          </button>
        ) : null}
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
            // 中文输入法组合态的 Enter 是确认候选词，不能当发送
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="mt-2 flex items-center justify-end gap-2">
          {sending ? <Spinner /> : null}
          <Button onClick={submit} disabled={!draft.trim() || sending || !sessionId}>
            {sending ? copy.playground.sendSending : copy.playground.send}
          </Button>
        </div>
      </div>
    </div>
  );
}
