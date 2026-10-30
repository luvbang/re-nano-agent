/**
 * hooks/useGlobalShortcuts 的可测部分（v0.2-4）：DOM 查询与"迟到聚焦"。
 *
 * node 环境没有真 DOM，用最小的假 document / 元素桩：
 * 这里要钉住的是「查什么标记」「兑现一次就清空请求」这两条行为，
 * 而不是浏览器焦点实现本身。
 */

import { describe, expect, it, vi } from "vitest";
import {
  consumePendingComposerFocus,
  focusComposer,
  requestComposerFocus,
} from "./useGlobalShortcuts";

function fakeComposer(value = "草稿") {
  const el = {
    value,
    focused: false,
    selection: null as null | [number, number],
    focus() {
      this.focused = true;
    },
    setSelectionRange(start: number, end: number) {
      this.selection = [start, end];
    },
  };
  const doc = {
    querySelector: (sel: string) => (sel === "[data-composer]" ? el : null),
  } as unknown as Document;
  return { el, doc };
}

describe("focusComposer", () => {
  it("按 data-composer 标记找到输入框并聚焦，光标落在草稿末尾", () => {
    const { el, doc } = fakeComposer("你好");
    expect(focusComposer(doc)).toBe(true);
    expect(el.focused).toBe(true);
    expect(el.selection).toEqual([2, 2]);
  });

  it("页面里没有 composer（比如停在 Keys 页）时返回 false，不抛错", () => {
    const empty = { querySelector: () => null } as unknown as Document;
    expect(focusComposer(empty)).toBe(false);
  });
});

describe("requestComposerFocus / consumePendingComposerFocus", () => {
  it("当场能找到就立刻聚焦，不留下待办", () => {
    const { el, doc } = fakeComposer();
    vi.stubGlobal("document", doc);
    try {
      requestComposerFocus();
      expect(el.focused).toBe(true);
      expect(consumePendingComposerFocus()).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("找不到时记下待办，页面挂载后兑现一次随即清空", () => {
    const empty = { querySelector: () => null } as unknown as Document;
    vi.stubGlobal("document", empty);
    try {
      requestComposerFocus();
      // composer 还没渲染，此时兑现不成功
      expect(consumePendingComposerFocus()).toBe(false);

      // 导航完成后 composer 出现，下一次挂载把它兑现
      const { el, doc } = fakeComposer();
      vi.stubGlobal("document", doc);
      expect(consumePendingComposerFocus()).toBe(true);
      expect(el.focused).toBe(true);
      // 只兑现一次：之后的普通渲染不该抢焦点
      expect(consumePendingComposerFocus()).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("没人请求过时 consume 直接返回 false", () => {
    const { doc } = fakeComposer();
    vi.stubGlobal("document", doc);
    try {
      // 先消费掉可能残留的上一个用例状态
      consumePendingComposerFocus();
      expect(consumePendingComposerFocus()).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
