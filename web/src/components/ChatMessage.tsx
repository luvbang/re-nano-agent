/** 对话气泡：用户右侧、assistant 左侧（含工具卡与流式光标）。memo 化：流式期间只有最后一段重渲染。 */

import { memo } from "react";
import type { ChatItem } from "../projection/run-projection";
import { StreamText } from "./StreamText";
import { ToolCallCard } from "./ToolCallCard";

export const ChatMessageView = memo(function ChatMessageView({ item }: { item: ChatItem }) {
  if (item.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-accent-dim px-3 py-2 text-sm text-emerald-50">
          {item.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      {item.tools.map((tool) => (
        <ToolCallCard key={tool.tool_call_id} tool={tool} />
      ))}
      {item.text || item.streaming ? (
        <div className="max-w-[95%] whitespace-pre-wrap rounded-lg bg-surface-raised px-3 py-2 text-sm leading-relaxed text-zinc-100">
          <StreamText text={item.text} streaming={item.streaming} />
        </div>
      ) : null}
    </div>
  );
});
