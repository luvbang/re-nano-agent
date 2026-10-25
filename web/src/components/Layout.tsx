/** 应用布局：左侧导航 + 顶栏（模式徽标 / 退出）。 */

import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { useAdminKey } from "../hooks/useAdminKey";
import { copy } from "../lib/copy";
import { Badge, Button } from "./ui";

export function Layout({ children }: { children: ReactNode }) {
  const { mode, signOut } = useAdminKey();
  const navigate = useNavigate();
  const navItems = [
    { to: "/playground", label: copy.nav.playground },
    { to: "/sessions", label: copy.nav.sessions },
    { to: "/keys", label: copy.nav.keys },
    { to: "/usage", label: copy.nav.usage },
    { to: "/status", label: copy.nav.status },
  ];
  return (
    <div className="flex h-screen">
      <aside className="flex w-52 shrink-0 flex-col border-r border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-4">
          <div className="text-base font-semibold">{copy.app.title}</div>
          <div className="text-xs text-zinc-500">{copy.app.subtitle}</div>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-accent-dim text-emerald-200"
                    : "text-zinc-400 hover:bg-surface hover:text-zinc-200"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-surface-border p-3">
          {mode === "demo" ? <Badge tone="warn">{copy.state.demoBadge}</Badge> : null}
          <Button
            variant="ghost"
            className="mt-2 w-full"
            onClick={() => {
              signOut();
              navigate("/login");
            }}
          >
            {copy.nav.logout}
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        {mode === "demo" ? (
          <div className="border-b border-amber-900/50 bg-amber-950/40 px-4 py-1.5 text-center text-xs text-amber-300">
            {copy.state.demoBanner}
          </div>
        ) : null}
        {children}
      </main>
    </div>
  );
}
