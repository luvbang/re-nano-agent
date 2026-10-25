/**
 * 应用布局：nanobot 形态工作台——左侧栏（🍁 品牌 / 搜索 / 新话题 / Topics 列表 /
 * 底部管理导航与退出）+ 右侧主区（demo 横幅 + 页面）。
 * 会话列表走 Playground 同一客户端（项目 key 优先），选中态由 URL ?session= 驱动。
 * 视觉：单一地色 + 1px 结构线；选中项只由同一根 1px 琥珀线 + 文字变亮标记（data-terminal move）。
 * 手机/平板（<1024px）侧栏折叠为顶栏 + 全屏抽屉（app-screens §12）。
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate, useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAdminKey } from "../hooks/useAdminKey";
import { copy } from "../lib/copy";
import { Badge, Button } from "./ui";
import { MapleMark, MagnifierIcon, MenuIcon } from "./icons";
import { TopicSearchDialog } from "./TopicSearchDialog";

const WIDTH_STORAGE = "agentd.sidebarWidth";
const MIN_W = 208;
const MAX_W = 400;
const DEFAULT_W = 264;
const FOLD_MQ = "(max-width: 1023px)";

function useFolded(): boolean {
  const [folded, setFolded] = useState(
    () => typeof window !== "undefined" && window.matchMedia(FOLD_MQ).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(FOLD_MQ);
    const onChange = () => setFolded(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return folded;
}

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
          className="w-full rounded-md border border-control bg-ground px-2 py-1.5 text-sm text-ink focus:outline-none"
        />
      ) : (
        <div
          className={`flex items-center rounded-md pr-1 transition-colors ${
            active ? "sel-left text-white" : "text-mut hover:bg-raised hover:text-ink"
          }`}
        >
          <button
            type="button"
            onClick={onOpen}
            title={title ?? copy.sidebar.untitled}
            className="min-w-0 flex-1 truncate px-2.5 py-1.5 text-left text-sm"
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
                className="flex h-6 w-6 items-center justify-center rounded text-sm text-mut hover:bg-line hover:text-ink"
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
                  <div className="absolute right-0 z-30 mt-1 w-28 overflow-hidden rounded-lg border border-line bg-raised py-1 shadow-pop">
                    <button
                      type="button"
                      className="block w-full px-3 py-1.5 text-left text-sm text-ink hover:bg-ground"
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
                      className="block w-full px-3 py-1.5 text-left text-sm text-neg hover:bg-ground"
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
  const [sheetOpen, setSheetOpen] = useState(false);
  const folded = useFolded();
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

  /** 侧栏内容（桌面 aside 与手机抽屉共用） */
  const sidebarBody = (
    <>
      {/* 品牌 + 全局动作 */}
      <div className="flex items-center gap-2.5 px-3 pb-2 pt-4">
        <MapleMark className="h-6 w-6 text-accent" />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-base font-semibold text-white">{copy.app.title}</div>
          <div className="truncate text-xs text-mut">{copy.app.subtitle}</div>
        </div>
        <button
          type="button"
          title={copy.sidebar.searchTopics}
          aria-label={copy.sidebar.searchTopics}
          onClick={() => setSearchOpen(true)}
          className="flex h-7 w-7 items-center justify-center rounded-md text-mut transition-colors hover:bg-raised hover:text-ink"
        >
          <MagnifierIcon />
        </button>
      </div>

      <div className="px-3 pb-2 pt-1">
        <button
          type="button"
          onClick={() => void newTopic()}
          disabled={!pgClient}
          className="flex h-8 w-full items-center justify-center gap-1.5 rounded-full border border-line px-3 text-sm font-medium text-ink transition-colors hover:border-control hover:bg-raised disabled:opacity-40"
        >
          ＋ {copy.sidebar.newTopic}
        </button>
      </div>

      {/* Topics */}
      <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2">
        <p className="px-2 pb-1 text-xs text-mut">{copy.sidebar.topics}</p>
        {!pgClient ? (
          <div className="px-2 py-3">
            <p className="text-sm leading-relaxed text-mut">{copy.sidebar.bindKeyHint}</p>
            <button
              type="button"
              onClick={() => navigate("/keys")}
              className="mt-2 text-sm text-ink underline underline-offset-2 hover:text-accent"
            >
              {copy.sidebar.bindKeyAction} →
            </button>
          </div>
        ) : sessionsQuery.isLoading ? (
          <p className="px-2 py-2 text-sm text-mut">…</p>
        ) : sessions.length === 0 ? (
          <p className="px-2 py-2 text-sm leading-relaxed text-mut">{copy.sidebar.emptyTopics}</p>
        ) : (
          <ul className="space-y-0.5 pb-2">
            {sessions.map((s) => (
              <TopicRow
                key={s.id}
                title={s.title}
                active={s.id === activeSession}
                onOpen={() => {
                  navigate(`/playground?session=${s.id}`);
                  setSheetOpen(false);
                }}
                onRenamed={(title) => renameTopic(s.id, title)}
                onDeleted={() => deleteTopic(s.id)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* 底部：管理导航 + 退出 */}
      <div className="border-t border-line px-2 py-2">
        <nav className="mb-1 flex flex-col">
          {adminItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setSheetOpen(false)}
              className={({ isActive }) =>
                `relative rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                  isActive
                    ? "sel-left bg-raised text-white"
                    : "text-mut hover:bg-raised hover:text-ink"
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
            variant="text"
            className="ml-auto !h-7 !px-2"
            onClick={() => {
              signOut();
              navigate("/login");
            }}
          >
            {copy.nav.logout}
          </Button>
        </div>
      </div>
    </>
  );

  return (
    <div className="flex h-screen flex-col bg-ground text-ink">
      {/* 折叠态顶栏（<1024px）：产品名 + 搜索 + 菜单 */}
      {folded ? (
        <header className="flex h-12 shrink-0 items-center gap-2.5 border-b border-line px-3">
          <MapleMark className="h-5 w-5 text-accent" />
          <span className="min-w-0 flex-1 truncate text-base font-semibold text-white">
            {copy.app.title}
          </span>
          <button
            type="button"
            title={copy.sidebar.searchTopics}
            aria-label={copy.sidebar.searchTopics}
            onClick={() => setSearchOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-mut transition-colors hover:bg-raised hover:text-ink"
          >
            <MagnifierIcon />
          </button>
          <button
            type="button"
            title={copy.nav.menu}
            aria-label={copy.nav.menu}
            onClick={() => setSheetOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-mut transition-colors hover:bg-raised hover:text-ink"
          >
            <MenuIcon className="h-5 w-5" />
          </button>
        </header>
      ) : null}

      <div className="flex min-h-0 flex-1">
        {!folded ? (
          <aside
            className="relative flex shrink-0 flex-col border-r border-line"
            style={{ width }}
          >
            {sidebarBody}
            {/* 拖拽调宽手柄 */}
            <div
              role="separator"
              aria-label="resize sidebar"
              onMouseDown={beginDrag}
              className="absolute inset-y-0 right-0 z-10 w-1 cursor-col-resize transition-colors hover:bg-accent"
            />
          </aside>
        ) : null}

        <main className="min-w-0 flex-1 overflow-auto">
          {mode === "demo" ? (
            <div className="border-b border-line bg-pill-warn px-4 py-1.5 text-center text-xs text-warn">
              {copy.state.demoBanner}
            </div>
          ) : null}
          {children}
        </main>
      </div>

      {/* 折叠态全屏抽屉：导航 / 话题 / 退出 */}
      {folded && sheetOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/60"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSheetOpen(false);
          }}
        >
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-line bg-ground shadow-pop">
            {sidebarBody}
          </aside>
        </div>
      ) : null}

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
