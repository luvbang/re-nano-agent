/**
 * Playground：nanobot 形态对话工作台。会话选择在左侧栏（URL ?session= 驱动），
 * 本页负责：会话头（标题/搜索/停止）、消息流（历史 + 本轮流式投影）、composer。
 * 草稿话题：无会话时发送首条消息自动建会话（标题取消息），免手动「新会话」。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { useRunStream } from "../hooks/useRunStream";
import { historyToItems, type ChatItem } from "../projection/run-projection";
import { ChatMessageView } from "../components/ChatMessage";
import { MessageSearchDialog } from "../components/MessageSearchDialog";
import { Badge, Button, Spinner } from "../components/ui";
import { copy } from "../lib/copy";
import type { Usage } from "../api/types";

/** 只有用户本来就在底部附近时才自动跟随滚动（否则会被流式输出强行拽回） */
const PIN_THRESHOLD_PX = 60;

export function PlaygroundPage() {
  const { client, playgroundClient, playgroundKey, setPlaygroundKey, mode } = useAdminKey();
  // 全部请求使用绑定的项目 key（无绑定则回落管理员 key），保证会话/消息同一 project 作用域
  const pgClient = playgroundClient ?? client;
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSession = searchParams.get("session");
  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [draft, setDraft] = useState("");
  const [pinned, setPinned] = useState(true);
  const [lastUsage, setLastUsage] = useState<Usage | null>(null);
  const [msgSearchOpen, setMsgSearchOpen] = useState(false);
  const lastInputRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

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
  useEffect(() => {
    if (projection.phase !== "completed" || sessionId === null) return;
    let cancelled = false;
    void (async () => {
      await queryClient.invalidateQueries({
        queryKey: ["pg-messages", mode, playgroundKey, sessionId],
      });
      if (!cancelled) reset();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projection.phase, sessionId]);

  // 完成后把本轮用量留存在页面上，直到下次发送
  useEffect(() => {
    if (projection.phase === "completed" && projection.usage) setLastUsage(projection.usage);
  }, [projection.phase, projection.usage]);

  // URL 带 session 参数时优先；否则自动选最近一个（与侧栏高亮一致）
  useEffect(() => {
    if (urlSession) {
      if (urlSession !== sessionId) {
        reset();
        setLastUsage(null);
        setSessionId(urlSession);
      }
      return;
    }
    if (sessionId === null && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setSessionId(sessionsQuery.data[0]!.id);
    }
  }, [urlSession, sessionId, sessionsQuery.data, reset]);

  const sessionTitle = useMemo(
    () => sessionsQuery.data?.find((s) => s.id === sessionId)?.title ?? null,
    [sessionsQuery.data, sessionId],
  );

  const historyItems = useMemo(() => historyToItems(historyQuery.data ?? []), [historyQuery.data]);

  const items: ChatItem[] = useMemo(() => {
    if (projection.phase === "idle") return historyItems;
    if (
      (projection.phase === "failed" || projection.phase === "cancelled") &&
      projection.items.length === 0
    ) {
      return historyItems;
    }
    return [...historyItems, ...projection.items];
  }, [historyItems, projection]);

  // sticky-bottom：仅在用户贴近底部时跟随
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

  const shrinkComposer = () => {
    const el = composerRef.current;
    if (el) el.style.height = "auto";
  };

  const submit = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setLastUsage(null);
    lastInputRef.current = text;
    setPinned(true);
    shrinkComposer();
    try {
      if (!sessionId) {
        // 草稿话题：首条消息即标题
        const s = await pgClient.createSession({ title: text.slice(0, 60) });
        setSessionId(s.id);
        setSearchParams({ session: s.id }, { replace: true });
        void queryClient.invalidateQueries({ queryKey: ["pg-sessions"] });
        void queryClient.invalidateQueries({ queryKey: ["sidebar-sessions"] });
        await send(text, { sessionId: s.id });
      } else {
        await send(text);
      }
    } catch {
      // createSession 失败等场景：useRunStream/页面各自收敛，这里不额外处理
    }
  };

  const showFailedBar = projection.phase === "failed" && projection.error !== null;
  const showCancelledBar = projection.phase === "cancelled" && projection.items.length > 0;
  const usage = projection.phase === "completed" ? projection.usage : lastUsage;
  const showHero = items.length === 0 && !sending && !showFailedBar;

  return (
    <div className="flex h-full min-w-0 flex-col">
      {/* 会话头 */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-surface-border px-4">
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">
          {sessionTitle ?? copy.sidebar.untitled}
        </h1>
        <button
          type="button"
          title={copy.messageSearch.open}
          aria-label={copy.messageSearch.open}
          onClick={() => setMsgSearchOpen(true)}
          disabled={items.length === 0}
          className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-surface-raised hover:text-zinc-200 disabled:opacity-40"
        >
          🔍
        </button>
        {sending ? (
          <Button variant="danger" className="!px-2.5 !py-1 !text-xs" onClick={() => void cancel()}>
            ■ {copy.playground.stop}
          </Button>
        ) : null}
        {playgroundKey ? (
          <Badge tone="warn">
            <span className="flex items-center gap-1.5 text-[11px]">
              {copy.playground.projectKeyBadge(playgroundKey.slice(0, 10))}
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
      </header>

      {/* 消息流 */}
      <div className="relative min-h-0 flex-1">
        <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {showHero ? (
              <div className="flex h-[52vh] flex-col items-center justify-center gap-3 text-center">
                <span className="text-5xl">{copy.app.brand}</span>
                <h2 className="text-xl font-semibold text-zinc-100">
                  {copy.playground.emptyTitle}
                </h2>
                <p className="max-w-sm text-xs leading-relaxed text-zinc-500">
                  {copy.playground.emptySubtitle}
                </p>
              </div>
            ) : (
              items.map((item, i) => (
                <ChatMessageView
                  key={i < historyItems.length ? `h-${item.id ?? i}` : `live-${i}`}
                  item={item}
                />
              ))
            )}
            {showFailedBar && projection.error ? (
              <div className="flex items-center gap-3 rounded-lg border border-red-900/70 bg-red-950/40 px-3 py-2 text-xs text-red-300">
                <span className="flex-1">
                  {copy.playground.failedBar(projection.error.code, projection.error.message)}
                </span>
                {projection.error.retryable && lastInputRef.current ? (
                  <Button
                    variant="ghost"
                    className="!px-2 !py-1 !text-xs"
                    onClick={() => void send(lastInputRef.current!)}
                  >
                    {copy.playground.retry}
                  </Button>
                ) : null}
              </div>
            ) : null}
            {showCancelledBar ? (
              <div className="rounded-lg border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
                {copy.playground.cancelledBar}
              </div>
            ) : null}
            <div className="h-2" />
          </div>
        </div>
        {!pinned ? (
          <button
            type="button"
            onClick={() => {
              setPinned(true);
              const el = scrollRef.current;
              if (el) el.scrollTop = el.scrollHeight;
            }}
            className="absolute bottom-4 left-1/2 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border border-surface-border bg-surface-raised text-xs text-zinc-300 shadow-card transition-colors hover:text-zinc-100"
            aria-label="scroll to bottom"
          >
            ↓
          </button>
        ) : null}
      </div>

      {/* composer */}
      <div className="shrink-0 px-4 pb-4">
        <form
          className="mx-auto max-w-3xl rounded-2xl border border-surface-border bg-surface-raised p-3 shadow-card transition-colors focus-within:border-accent/60"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <textarea
            ref={composerRef}
            value={draft}
            rows={1}
            placeholder={copy.playground.inputPlaceholder}
            onChange={(e) => setDraft(e.target.value)}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 192)}px`;
            }}
            onKeyDown={(e) => {
              // 中文输入法组合态的 Enter 是确认候选词，不能当发送
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            className="max-h-48 w-full resize-none bg-transparent px-1 text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
          />
          <div className="mt-2 flex items-center gap-2 px-1">
            {sending ? (
              <span className="flex items-center gap-2 text-[11px] text-zinc-500">
                <Spinner className="!h-3 !w-3" />
                {copy.playground.sendSending}
              </span>
            ) : usage ? (
              <Badge tone="success" className="!text-[10px]">
                {copy.playground.usageBar(usage.input_tokens, usage.output_tokens)}
              </Badge>
            ) : null}
            <span className="flex-1" />
            {sending ? (
              <Button variant="danger" className="!px-3 !py-1.5 !text-xs" onClick={() => void cancel()}>
                ■ {copy.playground.stop}
              </Button>
            ) : (
              <Button type="submit" disabled={!draft.trim()}>
                {copy.playground.send}
              </Button>
            )}
          </div>
        </form>
      </div>

      {msgSearchOpen ? (
        <MessageSearchDialog items={items} onClose={() => setMsgSearchOpen(false)} />
      ) : null}
    </div>
  );
}
