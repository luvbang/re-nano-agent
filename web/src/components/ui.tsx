/** 手写 Tailwind 原语（v0.1 不引组件库；shadcn 化留给 v0.2 打磨）。 */

import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-line bg-panel p-4 ${className}`}>{children}</div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles =
    variant === "primary"
      ? "bg-accent text-base hover:opacity-90"
      : variant === "danger"
        ? "border border-red-500/60 text-red-400 hover:bg-red-500/10"
        : "border border-line text-dim hover:text-ink";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded border border-line bg-base px-3 py-1.5 text-sm text-ink placeholder:text-dim/60 focus:border-accent focus:outline-none ${props.className ?? ""}`}
    />
  );
}

export function Badge({ tone, children }: { tone: "ok" | "bad" | "muted"; children: ReactNode }) {
  const cls =
    tone === "ok"
      ? "bg-emerald-500/15 text-emerald-400"
      : tone === "bad"
        ? "bg-red-500/15 text-red-400"
        : "bg-line/40 text-dim";
  return <span className={`rounded px-2 py-0.5 text-xs ${cls}`}>{children}</span>;
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-dim">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-dim border-t-transparent" />
      {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-line py-8 text-center text-sm text-dim">
      {children}
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
      {children}
    </div>
  );
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="mb-4 text-lg font-semibold text-ink">{children}</h1>;
}
