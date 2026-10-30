/**
 * Playground：nanobot 形态对话工作台。会话选择在左侧栏（URL ?session= 驱动），
 * 本页负责：会话头（标题/搜索/停止）、消息流（历史 + 本轮流式投影）、composer。
 * 草稿话题：无会话时发送首条消息自动建会话（标题取消息），免手动「新会话」。
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { consumePendingComposerFocus } from "../hooks/useGlobalShortcuts";
import { useRunStream } from "../hooks/useRunStream";
import { historyToItems, type ChatItem } from "../projection/run-projection";
import { ChatMessageView } from "../components/ChatMessage";
import { MessageSearchDialog } from "../components/MessageSearchDialog";
import { Badge, Button, Spinner } from "../components/ui";
import { MapleMark, MagnifierIcon } from "../components/icons";
import { copy } from "../lib/copy";
import type { Usage } from "../api/types";

/** 只有用户本来就在底部附近时才自动跟随滚动（否则会被流式输出强行拽回） */
const PIN_THRESHOLD_PX = 60;

export function PlaygroundPage() {
  const { client, playgroundClient, playgroundKey, setPlaygroundKey, mode } = useAdminKey();
  // 项目级端点只吃 project scope：管理员 key 请求会 401 并触发全局登出，
  // 因此对话页仅在绑定项目 key 后工作，否则显示绑定引导
  const pgClient = playgroundClient;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSession = searchParams.get("session");
  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [draft, setDraft] = useState("");
  const [pinned, setPinned] = useState(true);
  const [lastUsage, setLastUsage] = useState<Usage | null>(null);
  const [msgSearchOpen, setMsgSearchOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const lastInputRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["pg-sessions", mode, playgroundKey],
    queryFn: () => pgClient!.listSessions(50),
    enabled: pgClient !== null,
  });

  const modelsQuery = useQuery({
    queryKey: ["pg-models", mode, playgroundKey],
    queryFn: () => pgClient!.listModels(),
    enabled: pgClient !== null,
  });
  const models = modelsQuery.data ?? [];
  const effectiveModel = selectedModel ?? models[0]?.id ?? null;

  const historyQuery = useQuery({
    queryKey: ["pg-messages", mode, playgroundKey, sessionId],
    queryFn: () => pgClient!.listMessages(sessionId!, { limit: 100 }),
    enabled: pgClient !== null && sessionId !== null,
  });

  const { projection, sending, send, cancel, reset } = useRunStream(
    pgClient ?? client,
    sessionId,
  );

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

  // 从别的页面按 `/` 会先导航到这里；composer 此刻才挂载，兑现那次聚焦请求。
  // 放在 layout effect 里：等 DOM 提交后再 focus，避免被后续渲染抢走焦点。
  // 未绑定项目 Key 时 composer 还没渲染，先保留请求，绑定后自然兑现。
  useLayoutEffect(() => {
    if (pgClient === null) return;
    consumePendingComposerFocus();
  }, [pgClient]);

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
    if (!pgClient) return;
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
        await send(text, { sessionId: s.id, model: effectiveModel });
      } else {
        await send(text, { model: effectiveModel });
      }
    } catch {
      // createSession 失败等场景：useRunStream/页面各自收敛，这里不额外处理
    }
  };

  const showFailedBar = projection.phase === "failed" && projection.error !== null;
  const showCancelledBar = projection.phase === "cancelled" && projection.items.length > 0;
  const usage = projection.phase === "completed" ? projection.usage : lastUsage;
  const showBindKey = pgClient === null;
  const showHero = !showBindKey && items.length === 0 && !sending && !showFailedBar;

  return (
    <div className="flex h-full min-w-0 flex-col">
      {/* 会话头 */}
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4 sm:px-6">
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-white">
          {sessionTitle ?? copy.sidebar.untitled}
        </h1>
        <button
          type="button"
          title={copy.messageSearch.open}
          aria-label={copy.messageSearch.open}
          onClick={() => setMsgSearchOpen(true)}
          disabled={items.length === 0}
          className="flex h-8 w-8 items-center justify-center rounded-md text-mut transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
        >
          <MagnifierIcon />
        </button>
        {sending ? (
          <Button variant="danger" className="!h-7 !px-3 !text-xs" onClick={() => void cancel()}>
            ■ {copy.playground.stop}
          </Button>
        ) : null}
        {playgroundKey ? (
          <Badge tone="warn" className="max-w-[52vw] sm:max-w-none">
            <span className="min-w-0 truncate">
              {copy.playground.projectKeyBadge(playgroundKey.slice(0, 10))}
            </span>
            <button
              type="button"
              className="flex-none underline underline-offset-2 hover:text-white"
              onClick={() => setPlaygroundKey(null)}
            >
              {copy.playground.useAdminKeyAgain}
            </button>
          </Badge>
        ) : null}
      </header>

      {/* 消息流 */}
      <div className="relative min-h-0 flex-1">
        <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
            {showBindKey ? (
              <div className="flex h-[52vh] flex-col items-center justify-center gap-3 text-center">
                <MapleMark className="h-10 w-10 text-accent" />
                <h2 className="text-xl font-semibold text-white">
                  {copy.playground.bindKeyTitle}
                </h2>
                <p className="max-w-sm text-sm leading-relaxed text-mut">
                  {copy.playground.bindKeyHint}
                </p>
                <Button onClick={() => navigate("/keys")}>
                  {copy.playground.bindKeyAction}
                </Button>
              </div>
            ) : showHero ? (
              <div className="flex h-[52vh] flex-col items-center justify-center gap-3 text-center">
                <MapleMark className="h-10 w-10 text-accent" />
                <h2 className="text-xl font-semibold text-white">
                  {copy.playground.emptyTitle}
                </h2>
                <p className="max-w-sm text-sm leading-relaxed text-mut">
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
              <div className="flex items-center gap-3 rounded-md border border-neg/30 bg-pill-neg px-3 py-2 text-sm text-neg">
                <span className="flex-1">
                  {copy.playground.failedBar(projection.error.code, projection.error.message)}
                </span>
                {projection.error.retryable && lastInputRef.current ? (
                  <Button
                    variant="ghost"
                    className="!h-7 !px-3 !text-xs"
                    onClick={() => void send(lastInputRef.current!)}
                  >
                    {copy.playground.retry}
                  </Button>
                ) : null}
              </div>
            ) : null}
            {showCancelledBar ? (
              <div className="rounded-md border border-warn/30 bg-pill-warn px-3 py-2 text-sm text-warn">
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
            className="absolute bottom-4 left-1/2 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border border-line bg-raised text-ink shadow-pop transition-colors hover:text-white"
            aria-label="scroll to bottom"
          >
            ↓
          </button>
        ) : null}
      </div>

      {/* composer */}
      <div className="shrink-0 px-4 pb-5 sm:px-6">
        <form
          className="mx-auto max-w-3xl rounded-lg border border-line bg-panel p-3 shadow-pop transition-colors focus-within:border-accent"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <textarea
            ref={composerRef}
            // 全局 `/` 快捷键按此标记查找焦点目标（Playground 是懒加载路由，
            // 从 Layout 传 ref 会穿透 Suspense，见 hooks/useGlobalShortcuts）
            data-composer=""
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
            className="max-h-48 w-full resize-none bg-transparent px-1 text-base leading-relaxed text-ink placeholder:text-mut focus:outline-none"
          />
          <div className="mt-2 flex items-center gap-2 px-1">
            {/* 模型选择 chip（nanobot 形态）：向上弹层列出可用模型 */}
            <div className="relative">
              <button
                type="button"
                title={copy.playground.modelLabel}
                onClick={() => setModelOpen((v) => !v)}
                className="flex h-7 items-center gap-1.5 rounded-full border border-line bg-ground px-2.5 text-xs text-mut transition-colors hover:border-control hover:text-ink"
              >
                <MapleMark className="h-3 w-3 text-accent" />
                <span className="max-w-28 truncate">{effectiveModel ?? copy.playground.modelLabel}</span>
              </button>
              {modelOpen ? (
                <>
                  <div className="fixed inset-0 z-20" onClick={() => setModelOpen(false)} />
                  <div className="absolute bottom-9 left-0 z-30 w-64 animate-fade-up overflow-hidden rounded-lg border border-line bg-raised py-1 shadow-pop">
                    <p className="px-3 pb-1 pt-1.5 text-xs text-mut">
                      {copy.playground.modelLabel}
                    </p>
                    {models.length === 0 ? (
                      <p className="px-3 py-2 text-sm text-mut">{copy.state.empty}</p>
                    ) : (
                      models.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => {
                            setSelectedModel(m.id);
                            setModelOpen(false);
                          }}
                          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-ground ${
                            m.id === effectiveModel ? "sel-left text-white" : "text-ink"
                          }`}
                        >
                          <span className="num flex-1 truncate">{m.id}</span>
                          {m.tools ? <span className="text-2xs text-mut">tools</span> : null}
                        </button>
                      ))
                    )}
                  </div>
                </>
              ) : null}
            </div>
            {sending ? (
              <span className="flex items-center gap-2 text-xs text-mut">
                <Spinner className="!h-3 !w-3" />
                {copy.playground.sendSending}
              </span>
            ) : usage ? (
              <Badge tone="neutral">
                <span className="num">{copy.playground.usageBar(usage.input_tokens, usage.output_tokens)}</span>
              </Badge>
            ) : null}
            <span className="flex-1" />
            {sending ? (
              <Button variant="danger" className="!h-7 !px-3 !text-xs" onClick={() => void cancel()}>
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
