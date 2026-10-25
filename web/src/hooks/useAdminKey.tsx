/**
 * Key 上下文（web-architecture §6）：
 * - 管理员 key 存 sessionStorage（关标签即失效，泄露面最小），用于全部管理页面
 * - playgroundKey 为可选的“项目 key”绑定（main 线 M6 能力）：仅 Playground 使用，
 *   体现最小权限；撤销/清空立即生效
 * - demo 模式为内存数据源标记
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { createApiClient } from "../api";
import type { ApiClient, ClientMode } from "../api";

const KEY_STORAGE = "agentd.adminKey";
const MODE_STORAGE = "agentd.clientMode";
const PLAYGROUND_KEY_STORAGE = "agentd.playgroundKey";

export interface AdminKeyContextValue {
  apiKey: string;
  mode: ClientMode;
  playgroundKey: string;
  setPlaygroundKey: (key: string | null) => void;
  signIn: (apiKey: string, mode: ClientMode) => void;
  signOut: () => void;
  client: ApiClient;
  /** Playground 专用客户端：绑定了项目 key 时用它，否则回落管理员 client */
  playgroundClient: ApiClient | null;
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
  const [playgroundKey, setPlaygroundKeyState] = useState<string>(
    () => readStored(PLAYGROUND_KEY_STORAGE) ?? "",
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
    sessionStorage.removeItem(PLAYGROUND_KEY_STORAGE);
    setApiKey("");
    setPlaygroundKeyState("");
    setMode("real");
  }, []);

  const setPlaygroundKey = useCallback((key: string | null) => {
    if (key) sessionStorage.setItem(PLAYGROUND_KEY_STORAGE, key);
    else sessionStorage.removeItem(PLAYGROUND_KEY_STORAGE);
    setPlaygroundKeyState(key ?? "");
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

  // 项目 key 仅在真实模式下生效；被撤销（401/403）时自动解绑
  const playgroundClient = useMemo(() => {
    if (mode !== "real" || !playgroundKey) return null;
    return createApiClient("real", {
      apiKey: playgroundKey,
      onUnauthorized: () => {
        sessionStorage.removeItem(PLAYGROUND_KEY_STORAGE);
        setPlaygroundKeyState("");
      },
    });
  }, [mode, playgroundKey]);

  const value = useMemo(
    () => ({ apiKey, mode, playgroundKey, setPlaygroundKey, signIn, signOut, client, playgroundClient }),
    [apiKey, mode, playgroundKey, setPlaygroundKey, signIn, signOut, client, playgroundClient],
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
