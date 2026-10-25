/**
 * Markdown 渲染（react-markdown + remark-gfm）。
 * 样式在 index.css 的 .md 容器规则里（表格/代码块/引用等），此处只做装配与安全默认。
 */

import { memo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const MarkdownView = memo(function MarkdownView({ text }: { text: string }) {
  return (
    <div className="md text-base text-ink">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
});
