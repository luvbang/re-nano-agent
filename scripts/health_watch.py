#!/usr/bin/env python
"""最小健康告警（M5 D4）：轮询 /healthz，连续 N 次失败即告警（日志 + 可选 webhook）。

用法：
    uv run python scripts/health_watch.py --base-url http://127.0.0.1:8000 \
        --interval 30 --fail-after 3 [--webhook https://hooks.example/xxx]

cron/systemd 常驻或定时跑均可；退出码 0=健康，1=已触发告警（便于接入外部监控）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import urllib.parse

import httpx

from agentd.security.ssrf import assert_public_url


def check(base_url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{base_url}/healthz", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body.get("status") == "ok", json.dumps(body, ensure_ascii=False)
    except Exception as exc:  # 网络/超时/非 JSON 都算失败
        return False, f"{type(exc).__name__}: {exc}"


def notify(webhook: str | None, message: str, *, allow_private: bool = False) -> None:
    if not webhook:
        return
    # 输入校验：仅接受 http(s) 且带主机的 URL；默认拒绝私网地址（防 SSRF 误配），
    # 内网告警通道用 --allow-private 显式放行
    parsed = urllib.parse.urlparse(webhook)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"webhook 已忽略（仅支持 http/https）: {webhook}")
        return
    if not allow_private:
        try:
            assert_public_url(webhook)
        except Exception:
            print("webhook 指向私网/保留地址已拦截（内网通道请加 --allow-private）")
            return
    payload = json.dumps({"text": message}).encode("utf-8")
    with contextlib.suppress(Exception):
        # 告警通道故障不阻塞本进程；URL 已过 scheme/公网校验
        httpx.post(
            webhook, content=payload, headers={"Content-Type": "application/json"}, timeout=5
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="agentd health watcher")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--fail-after", type=int, default=3)
    parser.add_argument("--webhook", default=None)
    parser.add_argument(
        "--allow-private", action="store_true", help="允许 webhook 指向私网/保留地址"
    )
    parser.add_argument("--once", action="store_true", help="单次检查后退出")
    args = parser.parse_args()

    consecutive = 0
    while True:
        ok, detail = check(args.base_url)
        if ok:
            if consecutive:
                print(f"recovered: {detail}")
            consecutive = 0
        else:
            consecutive += 1
            print(f"unhealthy({consecutive}/{args.fail_after}): {detail}", flush=True)
            if consecutive >= args.fail_after:
                message = f"[agentd] 健康检查连续 {consecutive} 次失败：{detail}"
                print(message, flush=True)
                notify(args.webhook, message, allow_private=args.allow_private)
                return 1
        if args.once:
            return 0 if ok else 1
        import time

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
