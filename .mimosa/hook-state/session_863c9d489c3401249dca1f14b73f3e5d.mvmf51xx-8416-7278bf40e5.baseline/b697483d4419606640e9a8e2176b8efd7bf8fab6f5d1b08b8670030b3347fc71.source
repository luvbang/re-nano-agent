/** 空/加载/错误三态的集中视图（web-architecture §2“组件 gallery”的最小落地）。 */

import type { ReactNode } from "react";
import { copy } from "../lib/copy";
import { Button, Spinner } from "./ui";

export function LoadingState({ label = copy.state.loading }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-zinc-400">
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyState({
  children,
  hint,
}: {
  children?: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-10 text-sm text-zinc-500">
      <div>{children ?? copy.state.empty}</div>
      {hint ? <div className="text-xs text-zinc-600">{hint}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-sm">
      <div className="text-red-300">
        {copy.state.error}：{message}
      </div>
      {onRetry ? (
        <Button variant="ghost" onClick={onRetry}>
          {copy.state.retry}
        </Button>
      ) : null}
    </div>
  );
}
