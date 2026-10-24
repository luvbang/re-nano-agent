import { useState } from "react";
import { HashRouter as Router, NavLink, Navigate, Route, Routes } from "react-router-dom";

import { KeysContext, loadKeys, type ConsoleKeys } from "./hooks/keys";
import { Keys } from "./pages/Keys";
import { Login } from "./pages/Login";
import { Playground } from "./pages/Playground";
import { Sessions } from "./pages/Sessions";
import { Status } from "./pages/Status";
import { Usage } from "./pages/Usage";

export function App() {
  const [keys, setKeys] = useState(loadKeys);
  const value = { adminKey: keys.adminKey, projectKey: keys.projectKey };
  if (!keys.adminKey) {
    return (
      <KeysContext.Provider value={value}>
        <Login onLogin={(adminKey) => setKeys({ ...keys, adminKey })} />
      </KeysContext.Provider>
    );
  }
  return (
    <KeysContext.Provider value={value}>
      <Router>
        <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4">
          <nav className="flex items-center gap-1 border-b border-line py-3 text-sm">
            <span className="mr-4 font-semibold text-accent">agentd</span>
            {[
              ["playground", "Playground"],
              ["sessions", "Sessions"],
              ["keys", "Keys"],
              ["usage", "Usage"],
              ["status", "Status"],
            ].map(([path, label]) => (
              <NavLink
                key={path}
                to={`/${path}`}
                className={({ isActive }) =>
                  `rounded px-3 py-1.5 ${isActive ? "bg-line/40 text-ink" : "text-dim hover:text-ink"}`
                }
              >
                {label}
              </NavLink>
            ))}
            <button
              type="button"
              className="ml-auto text-dim hover:text-ink"
              onClick={() => {
                sessionStorage.clear();
                setKeys({ adminKey: "", projectKey: "" });
              }}
            >
              登出
            </button>
          </nav>
          <main className="flex-1 py-6">
            <Routes>
              <Route path="/playground" element={<Playground />} />
              <Route path="/sessions" element={<Sessions />} />
              <Route path="/keys" element={<Keys onProjectKey={(patch) => setKeys((prev: ConsoleKeys) => ({ ...prev, ...patch }))} />} />
              <Route path="/usage" element={<Usage />} />
              <Route path="/status" element={<Status />} />
              <Route path="*" element={<Navigate to="/playground" replace />} />
            </Routes>
          </main>
        </div>
      </Router>
    </KeysContext.Provider>
  );
}
