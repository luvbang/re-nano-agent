/** 极简 UI 基元（仓库内组件，按需精简到按钮/卡片/输入/徽标）。 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "ghost" | "danger" | "text";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const base =
    "inline-flex h-8 items-center justify-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent disabled:opacity-40 disabled:pointer-events-none";
  const styles: Record<ButtonVariant, string> = {
    // 深色主题的主控件靠反白（白底黑字），品牌琥珀只留给选中线与数据
    primary: "bg-ink text-[#131217] hover:bg-white",
    ghost: "bg-transparent text-ink border border-line hover:bg-raised hover:border-control",
    danger: "bg-transparent text-neg border border-neg/60 hover:bg-pill-neg",
    text: "bg-transparent text-mut hover:text-ink",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  // 分隔靠 1px 结构线与色阶，静止的卡片不带阴影
  return <div className={`rounded-md border border-line bg-panel ${className}`}>{children}</div>;
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-9 w-full rounded-lg border border-control bg-ground px-3 text-sm text-ink
        placeholder:text-mut focus:border-accent focus:outline-none transition-colors ${className}`}
      {...props}
    />
  );
}

/** 状态 pill：同色相的深底浅字对（token 见 tailwind.config pill.*），flex:none 防挤压。 */
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
    neutral: "bg-pill-neutral text-[#bdbdc0] border-control",
    success: "bg-pill-pos text-pos border-pos/30",
    warn: "bg-pill-warn text-warn border-warn/30",
    error: "bg-pill-neg text-neg border-neg/30",
  } as const;
  return (
    <span
      className={`inline-flex h-5 flex-none items-center gap-1 whitespace-nowrap rounded-full border px-2 text-xs font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-control border-t-accent ${className}`}
      role="status"
      aria-label="loading"
    />
  );
}
