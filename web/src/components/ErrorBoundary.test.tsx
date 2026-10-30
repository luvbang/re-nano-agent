/**
 * ErrorBoundary 的可测契约（v0.2-4）。
 *
 * 为什么不用 @testing-library/react：项目没有引入 jsdom/Testing Library，
 * 也不该为三个断言新增依赖。这里直接实例化 class 组件（它是普通 JS 类），
 * 用 React.createElement 的产物检查降级 UI 的内容与结构。
 * 真正的"捕获渲染异常"由 React 保证，我们负责的是——状态迁移对不对、
 * 降级 UI 用的是不是 copy.ts 的文案、重试能不能把错误清掉。
 */

import { isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";
import { copy } from "../lib/copy";

type FallbackElement = ReactElement<Record<string, unknown>>;

/** 递归收集渲染树里的所有可见字符串，用来断言文案来源 */
function texts(node: ReactNode, out: string[] = []): string[] {
  if (typeof node === "string") {
    out.push(node);
    return out;
  }
  if (Array.isArray(node)) {
    for (const child of node) texts(child, out);
    return out;
  }
  if (isValidElement<Record<string, unknown>>(node)) {
    // 文案既可能走 children，也可能走 message/label 这类 props
    // （ErrorState 的 message 就是 prop），两边都收
    for (const [key, value] of Object.entries(node.props)) {
      if (key === "className" || key === "children") continue;
      if (typeof value === "string") out.push(value);
    }
    texts(node.props.children as ReactNode, out);
  }
  return out;
}

/** 按 type 或 aria/title 找按钮：降级 UI 的操作出口 */
function buttons(node: ReactNode, out: FallbackElement[] = []): FallbackElement[] {
  if (Array.isArray(node)) {
    for (const child of node) buttons(child, out);
    return out;
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    if (typeof node.type === "function" || typeof node.type === "string") {
      const el = node as FallbackElement;
      // Button 基元渲染成函数组件，直接按"有 onClick 的元素"收集
      if (typeof el.props.onClick === "function") out.push(el);
    }
    buttons((node as FallbackElement).props.children as ReactNode, out);
  }
  return out;
}

/** 构造一个已进入崩溃态的实例（不经 React 挂载，只测类自身的行为） */
function crashed(props: { children?: ReactNode; resetKey?: string; onReset?: () => void }) {
  const inst = new ErrorBoundary({ children: null, ...props });
  inst.state = { error: new Error("boom") };
  return inst;
}

/** 模拟 React 在换页时用新 props 重新渲染（props 在实例上是只读的，测试里强写） */
function rerender(inst: ErrorBoundary, next: { resetKey?: string; children?: ReactNode }) {
  (inst as unknown as { props: unknown }).props = { children: null, ...next };
}

describe("getDerivedStateFromError", () => {
  it("把抛出的错误放进 state（这是降级 UI 的唯一数据来源）", () => {
    const err = new Error("render blew up");
    expect(ErrorBoundary.getDerivedStateFromError(err)).toEqual({ error: err });
  });
});

describe("降级 UI", () => {
  it("未出错时原样渲染 children", () => {
    const inst = new ErrorBoundary({ children: "正常内容" });
    expect(inst.render()).toBe("正常内容");
  });

  it("文案全部来自 copy.ts，没有散落的中文字面量", () => {
    const all = texts(crashed({}).render());
    expect(all).toContain(copy.errorBoundary.title);
    expect(all).toContain(copy.errorBoundary.hint);
    expect(all).toContain(copy.state.retry);
    expect(all).toContain(copy.errorBoundary.backToPlayground);
  });

  it("展示原始错误信息，便于用户复现时上报", () => {
    const all = texts(crashed({}).render());
    // ErrorState 把 copy.state.error 与 message 拼在同一行
    expect(all.join(" ")).toContain("boom");
  });

  it("错误没有 message 时回落到 copy 里的未知错误文案", () => {
    const inst = new ErrorBoundary({ children: null });
    inst.state = { error: new Error("") };
    expect(texts(inst.render()).join(" ")).toContain(copy.errorBoundary.unknown);
  });

  it("提供重试与回对话两个出口", () => {
    expect(buttons(crashed({}).render()).length).toBeGreaterThanOrEqual(2);
  });
});

describe("reset", () => {
  it("重试清空错误态，并通知外部回调", () => {
    const onReset = vi.fn();
    const inst = crashed({ onReset });
    const setState = vi.fn();
    inst.setState = setState as unknown as typeof inst.setState;

    inst.reset();

    expect(setState).toHaveBeenCalledWith({ error: null });
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("换页（resetKey 变化）自动恢复：一次崩溃不会永久粘住整页", () => {
    const inst = crashed({ resetKey: "/usage" });
    rerender(inst, { resetKey: "/status" });
    const reset = vi.fn();
    inst.reset = reset;

    inst.componentDidUpdate({ children: null, resetKey: "/usage" });

    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("没出错时换页不做任何事（不干扰正常渲染）", () => {
    const inst = new ErrorBoundary({ children: null, resetKey: "/usage" });
    rerender(inst, { resetKey: "/status" });
    const reset = vi.fn();
    inst.reset = reset;

    inst.componentDidUpdate({ children: null, resetKey: "/usage" });

    expect(reset).not.toHaveBeenCalled();
  });

  it("resetKey 没变时不重置", () => {
    const inst = crashed({ resetKey: "/usage" });
    const reset = vi.fn();
    inst.reset = reset;

    inst.componentDidUpdate({ children: null, resetKey: "/usage" });

    expect(reset).not.toHaveBeenCalled();
  });
});
