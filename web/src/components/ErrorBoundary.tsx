/**
 * 渲染期崩溃兜底（v0.2-4）：单个页面挂掉不再白屏，侧栏与导航仍然可用。
 *
 * 为什么是 class：React 至今只有 class 组件能实现 componentDidCatch /
 * getDerivedStateFromError，hooks 没有等价物。
 *
 * 视觉复用 StateViews 的语言（1px 虚线框 + 一句话 + 幽灵按钮），但不用
 * <ErrorState>：它按"数据加载失败"排版（py-10、居中小字），而这里是整页
 * 崩溃，需要撑起内容区并给出可操作的两个出口（重试 / 回对话页）。
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { copy } from "../lib/copy";
import { ErrorState } from "./StateViews";
import { Button } from "./ui";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** 路由切换时变化：key 变了就自动清空错误态，避免一次崩溃永久粘住整页 */
  resetKey?: string;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 控制台是唯一能拿到组件栈的地方；后端没有前端错误上报端点，
    // 留着这行让用户复现时可以直接从 DevTools 取栈
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  componentDidUpdate(prev: ErrorBoundaryProps) {
    if (this.state.error !== null && prev.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  reset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    const { error } = this.state;
    if (error === null) return this.props.children;

    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <div className="w-full max-w-md rounded-lg border border-neg/30 bg-panel p-6">
          <h2 className="mb-1 text-base font-semibold text-white">{copy.errorBoundary.title}</h2>
          <p className="mb-4 text-sm leading-relaxed text-mut">{copy.errorBoundary.hint}</p>
          <ErrorState message={error.message || copy.errorBoundary.unknown} />
          <div className="mt-2 flex items-center justify-center gap-2">
            <Button onClick={this.reset}>{copy.state.retry}</Button>
            <Button
              variant="ghost"
              onClick={() => {
                this.reset();
                window.location.assign("/playground");
              }}
            >
              {copy.errorBoundary.backToPlayground}
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
