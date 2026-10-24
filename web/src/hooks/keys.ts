/** 双 key 模型（M6）：管理员 key 管资源，项目 key 跑 Playground/Sessions。
 * 两者都存 sessionStorage（关标签即失效，泄露面最小；撤销立即生效由后端保证）。 */

import { createContext, useContext } from "react";

const ADMIN_KEY = "agentd_console_admin_key";
const PROJECT_KEY = "agentd_console_project_key";

export interface ConsoleKeys {
  adminKey: string;
  projectKey: string;
}

export function loadKeys(): ConsoleKeys {
  return {
    adminKey: sessionStorage.getItem(ADMIN_KEY) ?? "",
    projectKey: sessionStorage.getItem(PROJECT_KEY) ?? "",
  };
}

export function saveKeys(keys: Partial<ConsoleKeys>): void {
  if (keys.adminKey !== undefined) {
    if (keys.adminKey) sessionStorage.setItem(ADMIN_KEY, keys.adminKey);
    else sessionStorage.removeItem(ADMIN_KEY);
  }
  if (keys.projectKey !== undefined) {
    if (keys.projectKey) sessionStorage.setItem(PROJECT_KEY, keys.projectKey);
    else sessionStorage.removeItem(PROJECT_KEY);
  }
}

export const KeysContext = createContext<ConsoleKeys>({ adminKey: "", projectKey: "" });

export function useKeys(): ConsoleKeys {
  return useContext(KeysContext);
}
