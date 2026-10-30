/**
 * 路由与守卫：未登录一律重定向 /login（key 在 sessionStorage，关标签即失效）。
 *
 * 首屏只带 登录页 / 布局 / Playground（默认落地页）；其余管理页按路由懒加载，
 * 各自成 chunk（含占用最大的图表页），首屏不为它们付下载时间
 * （体积预算见 docs/web-architecture.md §"规模预期"）。
 */

import { lazy, Suspense, type ReactElement } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { LoadingState } from "./components/StateViews";
import { useAdminKey } from "./hooks/useAdminKey";
import { LoginPage } from "./pages/LoginPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";

// 懒加载页面的 Suspense 边界放在 Layout 内部：切页时侧栏/顶栏不闪，
// fallback 复用统一的 LoadingState（与真数据加载态同一视觉）。
const SessionsPage = lazy(() =>
  import("./pages/SessionsPage").then((m) => ({ default: m.SessionsPage })),
);
const KeysPage = lazy(() => import("./pages/KeysPage").then((m) => ({ default: m.KeysPage })));
const UsagePage = lazy(() => import("./pages/UsagePage").then((m) => ({ default: m.UsagePage })));
const StatusPage = lazy(() =>
  import("./pages/StatusPage").then((m) => ({ default: m.StatusPage })),
);

function RequireAuth({ children }: { children: ReactElement }) {
  const { apiKey } = useAdminKey();
  const { pathname } = useLocation();
  if (!apiKey) return <Navigate to="/login" replace />;
  return (
    <Layout>
      {/* 边界在 Layout 内部、Suspense 外部：页面崩溃只换掉内容区，侧栏与导航
          仍可点；换页时 resetKey 变化会自动恢复。包住 Suspense 也顺带兜住
          懒加载 chunk 拉取失败（弱网下比渲染异常更常见）。 */}
      <ErrorBoundary resetKey={pathname}>
        <Suspense fallback={<LoadingState />}>{children}</Suspense>
      </ErrorBoundary>
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/playground"
        element={
          <RequireAuth>
            <PlaygroundPage />
          </RequireAuth>
        }
      />
      <Route
        path="/sessions"
        element={
          <RequireAuth>
            <SessionsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/keys"
        element={
          <RequireAuth>
            <KeysPage />
          </RequireAuth>
        }
      />
      <Route
        path="/usage"
        element={
          <RequireAuth>
            <UsagePage />
          </RequireAuth>
        }
      />
      <Route
        path="/status"
        element={
          <RequireAuth>
            <StatusPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/playground" replace />} />
    </Routes>
  );
}
