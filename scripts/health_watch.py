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
import urllib.request


def check(base_url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{base_url}/healthz", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body.get("status") == "ok", json.dumps(body, ensure_ascii=False)
    except Exception as exc:  # 网络/超时/非 JSON 都算失败
        return False, f"{type(exc).__name__}: {exc}"


def notify(webhook: str | None, message: str) -> None:
    if not webhook:
        return
    payload = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        webhook, data=payload, headers={"Content-Type": "application/json"}
    )
    with contextlib.suppress(Exception):
        urllib.request.urlopen(request, timeout=5)  # 告警通道故障不阻塞本进程


def main() -> int:
    parser = argparse.ArgumentParser(description="agentd health watcher")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--fail-after", type=int, default=3)
    parser.add_argument("--webhook", default=None)
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
                notify(args.webhook, message)
                return 1
        if args.once:
            return 0 if ok else 1
        import time

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
