#!/usr/bin/env python
"""性能基线（M7 D3）：首事件延迟（TTFT）、完成延迟、吞吐的分位报告。

对运行中的服务测量（fake provider 时反映的是**平台自身开销**——
模型延迟另计；这正是 Go/No-Go「首 token P95<3s（模型自身延迟除外」的口径）。

    BASE_URL=http://127.0.0.1:8000 ADMIN_KEY=agd_... \
        uv run python scripts/perf.py --concurrency 20 --runs 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import httpx


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = min(int(len(ordered) * ratio), len(ordered) - 1)
    return ordered[index]


async def timed_run(
    client: httpx.AsyncClient, headers: dict[str, str], semaphore: asyncio.Semaphore
) -> dict[str, float] | None:
    """返回 {create_ms, first_event_ms, complete_ms}；失败返回 None。"""
    async with semaphore:
        t0 = time.perf_counter()
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs",
            json={"input": "性能基线探测"},
            headers=headers,
        )
        if created.status_code != 202:
            return None
        run_id = created.json()["run_id"]
        t_created = time.perf_counter()

        first_event: float | None = None
        terminal = {"completed", "failed", "cancelled"}
        async with client.stream(
            "GET", f"/v1/runs/{run_id}/events", headers=headers
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                if first_event is None and "event: " in buffer:
                    first_event = time.perf_counter()
                if any(f"event: {name}" in buffer for name in terminal):
                    break
        t_done = time.perf_counter()
        if first_event is None:
            return None
        return {
            "create_ms": (t_created - t0) * 1000,
            "first_event_ms": (first_event - t_created) * 1000,
            "complete_ms": (t_done - t_created) * 1000,
        }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-key", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--runs", type=int, default=60)
    args = parser.parse_args()

    admin = {"Authorization": f"Bearer {args.admin_key}"}
    semaphore = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as client:
        project = (
            await client.post(
                "/v1/admin/projects", json={"name": f"perf-{int(time.time())}"}, headers=admin
            )
        ).json()
        key = (
            await client.post(
                "/v1/admin/keys",
                json={"project_id": project["id"], "rate_limit_per_min": 10000},
                headers=admin,
            )
        ).json()["key"]
        headers = {"Authorization": f"Bearer {key}"}
        results = await asyncio.gather(
            *(timed_run(client, headers, semaphore) for _ in range(args.runs))
        )
    elapsed = time.perf_counter() - started

    samples = [r for r in results if r is not None]
    report: dict[str, Any] = {
        "runs": args.runs,
        "ok": len(samples),
        "failed": args.runs - len(samples),
        "concurrency": args.concurrency,
        "wall_seconds": round(elapsed, 2),
        "throughput_rps": round(len(samples) / elapsed, 2),
    }
    for metric in ("create_ms", "first_event_ms", "complete_ms"):
        values = [s[metric] for s in samples]
        if values:
            report[metric] = {
                "p50": round(percentile(values, 0.50), 1),
                "p95": round(percentile(values, 0.95), 1),
                "p99": round(percentile(values, 0.99), 1),
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Go/No-Go 口径：首事件 P95 < 3000ms（模型延迟除外）
    ttft_p95 = report.get("first_event_ms", {}).get("p95")
    verdict = "PASS" if ttft_p95 is not None and ttft_p95 < 3000 else "CHECK"
    print(f"TTFT p95 = {ttft_p95}ms → {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
