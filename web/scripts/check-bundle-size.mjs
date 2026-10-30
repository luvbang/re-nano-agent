/**
 * bundle 体积预算守卫（docs/web-architecture.md §"规模预期"：bundle gzip < 250KB）。
 *
 * 口径与 `vite build` 的 "computing gzip size" 一致：对 dist 下每个 js/css/html
 * 文件各算一次 gzip（node:zlib 默认 level 6），再按字节累加——不是把文件拼起来
 * 算一次 gzip（那样会因为跨文件共享字典而低估）。因此脚本读数可与 build 输出逐块对齐。
 *
 * 用法：node scripts/check-bundle-size.mjs [--dir dist] [--budget 250] [--json]
 * 超预算时以退出码 1 结束，并打印每块大小（按体积降序）。
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { gzipSync } from "node:zlib";

const DEFAULT_BUDGET_KB = 250;
const EXTS = [".js", ".css", ".html"];

/** 极简 argv 解析：--dir <path> / --budget <kb> / --json */
function parseArgs(argv) {
  const args = { dir: "dist", budget: DEFAULT_BUDGET_KB, json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--dir") args.dir = argv[++i] ?? args.dir;
    else if (a === "--budget") args.budget = Number(argv[++i]);
    else if (a === "--json") args.json = true;
    else if (a === "--help" || a === "-h") {
      console.log("用法: node scripts/check-bundle-size.mjs [--dir dist] [--budget 250] [--json]");
      process.exit(0);
    } else {
      console.error(`未知参数: ${a}`);
      process.exit(2);
    }
  }
  if (!Number.isFinite(args.budget) || args.budget <= 0) {
    console.error(`--budget 需要正数（单位 KB），收到 ${args.budget}`);
    process.exit(2);
  }
  return args;
}

/** 递归收集 dist 下所有 js/css/html 文件（跳过 sourcemap 与其它资源） */
function collectFiles(root) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (EXTS.some((ext) => entry.name.endsWith(ext))) out.push(full);
    }
  };
  walk(root);
  return out;
}

const kb = (bytes) => bytes / 1000;
const args = parseArgs(process.argv.slice(2));

let files;
try {
  if (!statSync(args.dir).isDirectory()) throw new Error("不是目录");
  files = collectFiles(args.dir);
} catch (err) {
  console.error(`读取 ${args.dir} 失败：${err instanceof Error ? err.message : String(err)}`);
  console.error("先在 web/ 下执行 `npm run build`，或用 --dir 指定构建产物目录。");
  process.exit(2);
}

if (files.length === 0) {
  console.error(`${args.dir} 下没有 js/css/html 产物——先执行 \`npm run build\`。`);
  process.exit(2);
}

const rows = files
  .map((file) => {
    const raw = readFileSync(file);
    const gzip = gzipSync(raw).length;
    return { name: relative(args.dir, file).split("\\").join("/"), raw: raw.length, gzip };
  })
  .sort((a, b) => b.gzip - a.gzip);

const totalGzip = rows.reduce((n, r) => n + r.gzip, 0);
const totalRaw = rows.reduce((n, r) => n + r.raw, 0);
const budgetBytes = args.budget * 1000;
const over = totalGzip > budgetBytes;

if (args.json) {
  console.log(
    JSON.stringify(
      { budgetKb: args.budget, totalKb: +kb(totalGzip).toFixed(2), over, files: rows },
      null,
      2,
    ),
  );
} else {
  console.log(`bundle 体积（gzip，逐块累加）— 预算 ${args.budget} KB`);
  console.log("");
  console.log("  gzip        raw       文件");
  for (const r of rows) {
    console.log(
      `  ${kb(r.gzip).toFixed(2).padStart(8)} kB ${kb(r.raw).toFixed(2).padStart(9)} kB   ${r.name}`,
    );
  }
  console.log("");
  console.log(
    `  合计 ${kb(totalGzip).toFixed(2)} kB gzip（raw ${(totalRaw / 1024).toFixed(2)} KiB）` +
      ` / 预算 ${args.budget} KB · 剩余 ${kb(budgetBytes - totalGzip).toFixed(2)} kB`,
  );
}

if (over) {
  console.error(
    `\n✗ 超出预算：${kb(totalGzip).toFixed(2)} kB > ${args.budget} kB（多 ${kb(totalGzip - budgetBytes).toFixed(2)} kB）`,
  );
  console.error("  优先按路由/第三方依赖拆 chunk，而不是删功能。");
  process.exit(1);
}

if (!args.json) console.log("\n✓ 体积预算通过");
