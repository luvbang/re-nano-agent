/**
 * 对话消息视图：用户右侧枫叶色气泡、assistant 左侧无底色纯文本（nanobot 形态）。
 * memo 化：流式期间只有最后一段重渲染。悬停显示时间戳与复制按钮。
 */

import { memo, useState } from "react";
import type { ChatItem } from "../projection/run-projection";
import { copy } from "../lib/copy";
import { MarkdownView } from "./Markdown";
import { StreamText } from "./StreamText";
import { ToolCallCard } from "./ToolCallCard";

function hm(iso?: string | null): string | null {
  return iso ? iso.slice(11, 16) : null;
}

function HoverActions({ text, createdAt }: { text: string; createdAt?: string | null }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex shrink-0 items-center gap-1 self-end opacity-0 transition-opacity duration-150 group-hover/msg:opacity-100">
      {hm(createdAt) && (
        <span className="text-[10px] tabular-nums text-zinc-600">{hm(createdAt)}</span>
      )}
      <button
        type="button"
        title={copied ? copy.playground.copied : copy.playground.copyText}
        aria-label={copy.playground.copyText}
        onClick={() => {
          void navigator.clipboard
            .writeText(text)
            .then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1200);
            })
            .catch(() => undefined);
        }}
        className="rounded p-1 text-[11px] text-zinc-500 hover:bg-surface-raised hover:text-zinc-200"
      >
        {copied ? "✓" : "⧉"}
      </button>
    </div>
  );
}

export const ChatMessageView = memo(function ChatMessageView({ item }: { item: ChatItem }) {
  if (item.kind === "user") {
    return (
      <div className="group/msg flex animate-fade-up items-end gap-2" data-msg-id={item.id}>
        <div className="order-2 max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 px-3.5 py-2 text-sm leading-relaxed text-amber-50 ring-1 ring-accent/25">
          <p className="whitespace-pre-wrap break-words">{item.text}</p>
        </div>
        <div className="order-1 flex-1" />
        <div className="order-3">
          <HoverActions text={item.text} createdAt={item.createdAt} />
        </div>
      </div>
    );
  }
  return (
    <div className="group/msg flex animate-fade-up items-end gap-2" data-msg-id={item.id}>
      <div className="flex min-w-0 max-w-[95%] flex-col gap-1.5">
        {item.tools.map((tool) => (
          <ToolCallCard key={tool.tool_call_id} tool={tool} />
        ))}
        {item.text || item.streaming ? (
          item.streaming ? (
            <div className="text-sm leading-relaxed text-zinc-100">
              <StreamText text={item.text} streaming={item.streaming} />
            </div>
          ) : (
            <MarkdownView text={item.text} />
          )
        ) : null}
      </div>
      <div className="flex-1" />
      {item.text ? (
        <HoverActions text={item.text} createdAt={item.createdAt} />
      ) : null}
    </div>
  );
});
