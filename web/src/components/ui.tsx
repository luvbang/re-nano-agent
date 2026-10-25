/** 极简 UI 基元（shadcn 风格的仓库内组件，按需精简到按钮/卡片/输入/徽标）。 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none";
  const styles: Record<ButtonVariant, string> = {
    primary: "bg-accent text-zinc-950 hover:bg-accent-soft",
    ghost: "bg-transparent text-zinc-300 hover:bg-surface-raised border border-surface-border",
    danger: "bg-red-900/60 text-red-200 hover:bg-red-800/70 border border-red-900",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={`rounded-lg border border-surface-border bg-surface-raised shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm
        text-zinc-100 placeholder:text-zinc-500 focus:border-accent focus:outline-none ${className}`}
      {...props}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warn" | "error";
  className?: string;
}) {
  const tones = {
    neutral: "bg-zinc-800 text-zinc-300 border-zinc-700",
    success: "bg-emerald-900/50 text-emerald-300 border-emerald-800",
    warn: "bg-amber-900/50 text-amber-300 border-amber-800",
    error: "bg-red-900/50 text-red-300 border-red-800",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-600 border-t-accent ${className}`}
      role="status"
      aria-label="loading"
    />
  );
}
