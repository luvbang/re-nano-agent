"""同步客户端：复用异步实现，跑在专属后台事件循环线程上。

用法与 AsyncClient 完全一致（方法名相同）；stream() 是同步生成器。
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Iterator
from typing import Any

import httpx

from agentd_client.core import AsyncClient, MemoryStatus, StreamEvent


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="agentd-client-loop", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class Client:
    """同步 SDK 入口。close() 可省略（线程为 daemon），进程退出自动回收。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", *, api_key: str,
                 timeout_s: float = 60.0, max_retries: int = 3,
                 client: httpx.AsyncClient | None = None) -> None:
        self._runner = _LoopThread()
        self._async = AsyncClient(
            base_url, api_key=api_key, timeout_s=timeout_s, max_retries=max_retries,
            client=client,
        )

    def close(self) -> None:
        self._runner.run(self._async.aclose())
        self._runner.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- 请求/响应方法：一一对应 ----------

    def create_session(self, *, title: str | None = None,
                       external_user_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.create_session(
            title=title, external_user_id=external_user_id
        ))
        return result

    def get_session(self, session_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.get_session(session_id))
        return result

    def rename_session(self, session_id: str, *, title: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.rename_session(
            session_id, title=title
        ))
        return result

    def delete_session(self, session_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.delete_session(session_id))
        return result

    def list_messages(self, session_id: str, *, limit: int = 50,
                      before_seq: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.list_messages(
            session_id, limit=limit, before_seq=before_seq
        ))
        return result

    def create_run(self, session_id: str, *, input: str,
                   idempotency_key: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.create_run(
            session_id, input=input, idempotency_key=idempotency_key
        ))
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.get_run(run_id))
        return result

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.cancel_run(run_id))
        return result

    # ---------- memories ----------

    def list_memories(self, *, status: MemoryStatus | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
        raw: Any = self._runner.run(self._async.list_memories(status=status, limit=limit))
        return list(raw)

    def create_memory(self, *, content: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.create_memory(content=content))
        return result

    def archive_memory(self, memory_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.archive_memory(memory_id))
        return result

    def usage(self, *, group_by: str = "day", date_from: str | None = None,
              date_to: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._runner.run(self._async.usage(
            group_by=group_by, date_from=date_from, date_to=date_to
        ))
        return result

    def models(self) -> list[dict[str, Any]]:
        raw: Any = self._runner.run(self._async.models())
        return list(raw)

    def stream(self, run_id: str) -> Iterator[StreamEvent]:
        """同步 SSE 迭代器：后台协程把事件推进线程安全队列。"""
        events: queue.Queue[StreamEvent | None] = queue.Queue()
        future = asyncio.run_coroutine_threadsafe(
            self._fill(run_id, events), self._runner.loop
        )
        while True:
            item = events.get()
            if item is None:
                break
            yield item
        future.result()  # 透传异步侧异常（若有）

    async def _fill(self, run_id: str, events: queue.Queue[StreamEvent | None]) -> None:
        try:
            async for event in self._async.stream(run_id):
                events.put(event)
        finally:
            events.put(None)
