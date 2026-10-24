#!/usr/bin/env python
"""轻量并发压测（M3 D5）：N 个 session 并发跑 run，统计状态码分布与延迟分位。

用法：
    BASE_URL=http://127.0.0.1:8000 ADMIN_KEY=agd_xxx \
    uv run python scripts/loadtest.py --concurrency 20 --runs 40
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx


async def one_run(
    client: httpx.AsyncClient, admin_auth: dict[str, str], index: int
) -> tuple[int, float]:
    started = time.perf_counter()
    project = (
        await client.post(
            "/v1/admin/projects", json={"name": f"load-{index}"}, headers=admin_auth
        )
    ).json()
    key = (
        await client.post(
            "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin_auth
        )
    ).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}
    session = (await client.post("/v1/sessions", json={}, headers=auth)).json()
    created = await client.post(
        f"/v1/sessions/{session['id']}/runs",
        json={"input": f"压测第 {index} 条"},
        headers=auth,
    )
    if created.status_code != 202:
        return created.status_code, time.perf_counter() - started
    run_id = created.json()["run_id"]
    while True:
        await asyncio.sleep(0.05)
        run = (await client.get(f"/v1/runs/{run_id}", headers=auth)).json()
        if run["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return 200 if run["status"] == "completed" else 500, time.perf_counter() - started


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-key", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--runs", type=int, default=40)
    args = parser.parse_args()

    admin_auth = {"Authorization": f"Bearer {args.admin_key}"}
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as client:
        gate = asyncio.Semaphore(args.concurrency)

        async def guarded(index: int) -> tuple[int, float]:
            async with gate:
                return await one_run(client, admin_auth, index)

        results = await asyncio.gather(*(guarded(i) for i in range(args.runs)))
    elapsed = time.perf_counter() - started

    codes: dict[int, int] = {}
    latencies: list[float] = []
    for code, latency in results:
        codes[code] = codes.get(code, 0) + 1
        latencies.append(latency)
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]

    print(f"runs={args.runs} concurrency={args.concurrency} total={elapsed:.1f}s")
    print(f"status: {codes}")
    print(f"latency: p50={p50:.2f}s p95={p95:.2f}s")
    five_xx = sum(n for c, n in codes.items() if c >= 500)
    print("RESULT:", "PASS" if five_xx == 0 else f"FAIL({five_xx} 个 5xx)")
    return 0 if five_xx == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
