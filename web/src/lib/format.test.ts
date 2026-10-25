/** lib/format 纯函数测试（v0.2-4 起）：usageCsv 的契约与转义。 */

import { describe, expect, it } from "vitest";
import { formatCost, formatTokens, usageCsv } from "./format";

describe("usageCsv", () => {
  const items = [
    { bucket: "2026-10-24", runs: 3, input_tokens: 1200, output_tokens: 300, cost_usd: 0.0123 },
    { bucket: "gpt-4o-mini", runs: 9, input_tokens: 45000, output_tokens: 8800, cost_usd: 0.2 },
  ];

  it("表头带维度标签，行按字段顺序输出", () => {
    const csv = usageCsv(items, "日期");
    const lines = csv.split("\n");
    expect(lines[0]).toBe("日期,runs,input_tokens,output_tokens,cost_usd");
    expect(lines[1]).toBe("2026-10-24,3,1200,300,0.0123");
    expect(lines[2]).toBe("gpt-4o-mini,9,45000,8800,0.2");
  });

  it("含逗号/引号的 bucket 按 RFC 4180 转义", () => {
    const csv = usageCsv([{ bucket: 'a,"b",c', runs: 1, input_tokens: 1, output_tokens: 1, cost_usd: 0 }], "模型");
    expect(csv.split("\n")[1]).toBe('"a,""b"",c",1,1,1,0');
  });

  it("空明细只有表头", () => {
    expect(usageCsv([], "日期")).toBe("日期,runs,input_tokens,output_tokens,cost_usd");
  });
});

describe("展示格式化冒烟", () => {
  it("tokens/cost 分档", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(2_500_000)).toBe("2.50M");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.004)).toBe("$0.0040");
    expect(formatCost(1.5)).toBe("$1.50");
  });
});
