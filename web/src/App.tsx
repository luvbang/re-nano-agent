/** 路由与守卫：未登录一律重定向 /login（key 在 sessionStorage，关标签即失效）。 */

import { Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { useAdminKey } from "./hooks/useAdminKey";
import { KeysPage } from "./pages/KeysPage";
import { LoginPage } from "./pages/LoginPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { SessionsPage } from "./pages/SessionsPage";
import { StatusPage } from "./pages/StatusPage";
import { UsagePage } from "./pages/UsagePage";

function RequireAuth({ children }: { children: React.ReactElement }) {
  const { apiKey } = useAdminKey();
  if (!apiKey) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
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
