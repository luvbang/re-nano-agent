/**
 * 管理员 Key 上下文（web-architecture §6）：
 * sessionStorage 暂存（关标签即失效，泄露面最小），demo 模式为内存数据源标记。
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { createApiClient } from "../api";
import type { ApiClient, ClientMode } from "../api";

const KEY_STORAGE = "agentd.adminKey";
const MODE_STORAGE = "agentd.clientMode";

export interface AdminKeyContextValue {
  apiKey: string;
  mode: ClientMode;
  signIn: (apiKey: string, mode: ClientMode) => void;
  signOut: () => void;
  client: ApiClient;
}

const AdminKeyContext = createContext<AdminKeyContextValue | null>(null);

function readStored(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function AdminKeyProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string>(() => readStored(KEY_STORAGE) ?? "");
  const [mode, setMode] = useState<ClientMode>(
    () => (readStored(MODE_STORAGE) as ClientMode | null) ?? "real",
  );

  const signIn = useCallback((nextKey: string, nextMode: ClientMode) => {
    if (nextMode === "demo") {
      sessionStorage.setItem(MODE_STORAGE, "demo");
      // demo 模式不需要真实 key，但保留一个占位便于 UI 统一
      sessionStorage.setItem(KEY_STORAGE, nextKey || "agd_demo");
      setApiKey(nextKey || "agd_demo");
    } else {
      sessionStorage.setItem(MODE_STORAGE, "real");
      sessionStorage.setItem(KEY_STORAGE, nextKey);
      setApiKey(nextKey);
    }
    setMode(nextMode);
  }, []);

  const signOut = useCallback(() => {
    sessionStorage.removeItem(KEY_STORAGE);
    sessionStorage.removeItem(MODE_STORAGE);
    setApiKey("");
    setMode("real");
  }, []);

  const client = useMemo(
    () =>
      createApiClient(mode, {
        apiKey,
        onUnauthorized: () => {
          sessionStorage.removeItem(KEY_STORAGE);
          setApiKey("");
        },
      }),
    [mode, apiKey],
  );

  const value = useMemo(
    () => ({ apiKey, mode, signIn, signOut, client }),
    [apiKey, mode, signIn, signOut, client],
  );
  return <AdminKeyContext.Provider value={value}>{children}</AdminKeyContext.Provider>;
}

export function useAdminKey(): AdminKeyContextValue {
  const ctx = useContext(AdminKeyContext);
  if (!ctx) throw new Error("useAdminKey must be used within AdminKeyProvider");
  return ctx;
}

export function useAuthenticated(): boolean {
  const { apiKey } = useAdminKey();
  return apiKey.length > 0;
}
