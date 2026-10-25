/** 流式文本：流式期间尾部光标闪烁；完成后普通渲染。 */

export function StreamText({ text, streaming }: { text: string; streaming: boolean }) {
  if (!streaming) return <>{text}</>;
  return (
    <>
      {text}
      <span className="ml-0.5 inline-block h-4 w-[2px] animate-caret bg-accent align-text-bottom" />
    </>
  );
}
