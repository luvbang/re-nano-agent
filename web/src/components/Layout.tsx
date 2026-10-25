/**
 * 应用布局：nanobot 形态工作台——左侧栏（🍁 品牌 / 搜索 / 新话题 / Topics 列表 /
 * 底部管理导航与退出）+ 右侧主区（demo 横幅 + 页面）。
 * 会话列表走 Playground 同一客户端（项目 key 优先），选中态由 URL ?session= 驱动。
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate, useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { copy } from "../lib/copy";
import { Badge, Button } from "./ui";
import { TopicSearchDialog } from "./TopicSearchDialog";

const WIDTH_STORAGE = "agentd.sidebarWidth";
const MIN_W = 208;
const MAX_W = 400;
const DEFAULT_W = 264;

function useSidebarWidth() {
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(WIDTH_STORAGE));
    return saved >= MIN_W && saved <= MAX_W ? saved : DEFAULT_W;
  });
  const dragging = useRef<{ startX: number; startW: number } | null>(null);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(
        MAX_W,
        Math.max(MIN_W, dragging.current.startW + e.clientX - dragging.current.startX),
      );
      setWidth(next);
    };
    const onUp = () => {
      if (dragging.current) {
        dragging.current = null;
        localStorage.setItem(WIDTH_STORAGE, String(width));
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [width]);

  return { width, beginDrag: (e: React.MouseEvent) => {
    dragging.current = { startX: e.clientX, startW: width };
  } };
}

function TopicRow({
  title,
  active,
  onOpen,
  onRenamed,
  onDeleted,
}: {
  title: string | null;
  active: boolean;
  onOpen: () => void;
  onRenamed: (title: string) => Promise<void>;
  onDeleted: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title ?? "");
  const [menuOpen, setMenuOpen] = useState(false);

  const submit = async () => {
    setEditing(false);
    const next = draft.trim();
    if (!next || next === title) return;
    await onRenamed(next);
  };

  return (
    <li className="group/topic relative">
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void submit()}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") void submit();
            if (e.key === "Escape") setEditing(false);
          }}
          className="w-full rounded-md border border-accent/50 bg-surface px-2 py-1.5 text-xs text-zinc-100 focus:outline-none"
        />
      ) : (
        <div
          className={`flex items-center rounded-lg pr-1 transition-colors ${
            active ? "bg-accent/15" : "hover:bg-surface-raised"
          }`}
        >
          <button
            type="button"
            onClick={onOpen}
            title={title ?? copy.sidebar.untitled}
            className={`min-w-0 flex-1 truncate px-2.5 py-2 text-left text-xs ${
              active ? "text-amber-100" : "text-zinc-300"
            }`}
          >
            {title || copy.sidebar.untitled}
          </button>
          <div
            className={`${active ? "" : "opacity-0 transition-opacity group-hover/topic:opacity-100"}`}
          >
            <div className="relative">
              <button
                type="button"
                title={copy.sidebar.topicActions}
                aria-label={copy.sidebar.topicActions}
                onClick={() => setMenuOpen((v) => !v)}
                className="flex h-5 w-5 items-center justify-center rounded text-[11px] text-zinc-500 hover:bg-surface-border hover:text-zinc-200"
              >
                ⋯
              </button>
              {menuOpen ? (
                <>
                  <div
                    className="fixed inset-0 z-20"
                    onClick={() => setMenuOpen(false)}
                    onMouseDown={(e) => e.stopPropagation()}
                  />
                  <div className="absolute right-0 z-30 mt-1 w-28 overflow-hidden rounded-lg border border-surface-border bg-surface-raised py-1 shadow-pop">
                    <button
                      type="button"
                      className="block w-full px-3 py-1.5 text-left text-xs text-zinc-200 hover:bg-surface"
                      onClick={() => {
                        setMenuOpen(false);
                        setDraft(title ?? "");
                        setEditing(true);
                      }}
                    >
                      {copy.sidebar.rename}
                    </button>
                    <button
                      type="button"
                      className="block w-full px-3 py-1.5 text-left text-xs text-red-400 hover:bg-surface"
                      onClick={() => {
                        setMenuOpen(false);
                        void onDeleted();
                      }}
                    >
                      {copy.sidebar.delete}
                    </button>
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { mode, signOut, playgroundKey, playgroundClient } = useAdminKey();
  // 项目级端点（/v1/sessions*）只吃 project scope：管理员 key 会 401 且触发全局登出，
  // 侧栏仅在绑定项目 key 后加载话题，否则显示绑定引导
  const pgClient = playgroundClient;
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [searchOpen, setSearchOpen] = useState(false);
  const { width, beginDrag } = useSidebarWidth();

  const inPlayground = location.pathname === "/playground";
  const activeSession = inPlayground ? searchParams.get("session") : null;

  const sessionsQuery = useQuery({
    queryKey: ["sidebar-sessions", mode, playgroundKey],
    queryFn: () => pgClient!.listSessions(100),
    enabled: pgClient !== null,
  });
  const sessions = sessionsQuery.data ?? [];

  // 与 Playground 的 ["pg-sessions", ...] 缓存区分层：任一侧变更后互相失效
  const refreshSessions = () => {
    void queryClient.invalidateQueries({ queryKey: ["sidebar-sessions"] });
    void queryClient.invalidateQueries({ queryKey: ["pg-sessions"] });
  };

  const newTopic = async () => {
    if (!pgClient) return;
    const s = await pgClient.createSession({});
    refreshSessions();
    navigate(`/playground?session=${s.id}`);
  };

  const renameTopic = async (id: string, title: string) => {
    if (!pgClient) return;
    try {
      await pgClient.renameSession(id, title);
      refreshSessions();
    } catch (e) {
      window.alert(copy.sidebar.renameFailed(e instanceof Error ? e.message : String(e)));
    }
  };

  const deleteTopic = async (id: string) => {
    if (!pgClient) return;
    if (!window.confirm(copy.sidebar.deleteConfirm)) return;
    try {
      await pgClient.deleteSession(id);
      refreshSessions();
      if (id === activeSession) navigate("/playground");
    } catch (e) {
      window.alert(copy.sidebar.deleteFailed(e instanceof Error ? e.message : String(e)));
    }
  };

  const adminItems = [
    { to: "/playground", label: copy.nav.playground },
    { to: "/sessions", label: copy.nav.sessions },
    { to: "/keys", label: copy.nav.keys },
    { to: "/usage", label: copy.nav.usage },
    { to: "/status", label: copy.nav.status },
  ];

  return (
    <div className="flex h-screen">
      <aside
        className="relative flex shrink-0 flex-col border-r border-surface-border bg-surface-raised"
        style={{ width }}
      >
        {/* 品牌 + 全局动作 */}
        <div className="flex items-center gap-2.5 px-3 pb-2 pt-4">
          <span className="flex h-8 w-8 select-none items-center justify-center rounded-xl bg-gradient-to-br from-accent/30 to-accent/10 text-lg ring-1 ring-accent/30">
            {copy.app.brand}
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-semibold text-zinc-50">{copy.app.title}</div>
            <div className="truncate text-[10px] text-zinc-500">{copy.app.subtitle}</div>
          </div>
          <button
            type="button"
            title={copy.sidebar.searchTopics}
            aria-label={copy.sidebar.searchTopics}
            onClick={() => setSearchOpen(true)}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-surface hover:text-zinc-200"
          >
            🔍
          </button>
        </div>

        <div className="px-3 pb-2 pt-1">
          <button
            type="button"
            onClick={() => void newTopic()}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent/15 px-3 py-2 text-xs font-medium text-amber-200 ring-1 ring-accent/30 transition-colors hover:bg-accent/25"
          >
            ＋ {copy.sidebar.newTopic}
          </button>
        </div>

        {/* Topics */}
        <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2">
          <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
            {copy.sidebar.topics}
          </p>
          {!pgClient ? (
            <div className="px-2 py-3">
              <p className="text-xs leading-relaxed text-zinc-500">{copy.sidebar.bindKeyHint}</p>
              <button
                type="button"
                onClick={() => navigate("/keys")}
                className="mt-2 text-xs text-amber-300 underline underline-offset-2 hover:text-amber-200"
              >
                {copy.sidebar.bindKeyAction} →
              </button>
            </div>
          ) : sessionsQuery.isLoading ? (
            <p className="px-2 py-2 text-xs text-zinc-600">…</p>
          ) : sessions.length === 0 ? (
            <p className="px-2 py-2 text-xs leading-relaxed text-zinc-600">
              {copy.sidebar.emptyTopics}
            </p>
          ) : (
            <ul className="space-y-0.5 pb-2">
              {sessions.map((s) => (
                <TopicRow
                  key={s.id}
                  title={s.title}
                  active={s.id === activeSession}
                  onOpen={() => navigate(`/playground?session=${s.id}`)}
                  onRenamed={(title) => renameTopic(s.id, title)}
                  onDeleted={() => deleteTopic(s.id)}
                />
              ))}
            </ul>
          )}
        </div>

        {/* 底部：管理导航 + 退出 */}
        <div className="border-t border-surface-border px-2 py-2">
          <nav className="mb-1 flex flex-col">
            {adminItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-lg px-2.5 py-1.5 text-xs transition-colors ${
                    isActive ? "bg-surface text-amber-200" : "text-zinc-500 hover:bg-surface hover:text-zinc-200"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-2 px-1 pt-1">
            {mode === "demo" ? <Badge tone="warn">{copy.state.demoBadge}</Badge> : null}
            <Button
              variant="ghost"
              className="ml-auto !px-2 !py-1 !text-xs"
              onClick={() => {
                signOut();
                navigate("/login");
              }}
            >
              {copy.nav.logout}
            </Button>
          </div>
        </div>

        {/* 拖拽调宽手柄 */}
        <div
          role="separator"
          aria-label="resize sidebar"
          onMouseDown={beginDrag}
          className="absolute inset-y-0 right-0 z-10 w-1 cursor-col-resize transition-colors hover:bg-accent/50"
        />
      </aside>

      <main className="min-w-0 flex-1 overflow-auto">
        {mode === "demo" ? (
          <div className="border-b border-amber-900/50 bg-amber-950/40 px-4 py-1.5 text-center text-xs text-amber-300">
            {copy.state.demoBanner}
          </div>
        ) : null}
        {children}
      </main>

      {searchOpen ? (
        <TopicSearchDialog
          sessions={sessions}
          currentId={activeSession}
          onClose={() => setSearchOpen(false)}
        />
      ) : null}
    </div>
  );
}
