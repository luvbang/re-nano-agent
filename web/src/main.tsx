import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { AdminKeyProvider } from "./hooks/useAdminKey";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 },
  },
});

// ?demo=1 直达离线演示模式（等价于登录页「进入离线演示模式」）：
// 供 e2e / 设计检查工具免登录进入全部页面，仅写 sessionStorage，不触后端
if (new URLSearchParams(window.location.search).has("demo")) {
  sessionStorage.setItem("agentd.clientMode", "demo");
  sessionStorage.setItem("agentd.adminKey", "agd_demo");
  sessionStorage.setItem("agentd.playgroundKey", "pk_demo_playground");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AdminKeyProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AdminKeyProvider>
    </QueryClientProvider>
  </StrictMode>,
);
