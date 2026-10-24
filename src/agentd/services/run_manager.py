"""RunManager（M3 D2）：runs 的后台执行、事件扇出与取消。

- per-session 串行：同 session 已有 run 在跑 → 新请求 409 conflict
- 全局 + per-project 信号量：超并发时 run 保持 queued，拿到槽位才 running
- 事件：先落库（控制类，带 seq）再广播给订阅者；delta/reasoning.delta 不落库只广播
- 取消：task.cancel() → run 置 cancelled，广播并持久化 run.cancelled 终态事件
- 崩溃恢复：进程重启时 lifespan 已把遗留 run 标 interrupted；SSE 订阅侧
  发现 run 非活跃且无持久化终态时合成 run.failed(interrupted)（见 routes/runs.py）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agentd.api.errors import AppError, ErrorCode
from agentd.providers.base import Provider
from agentd.runtime.events import (
    MessageCompleted,
    MessageDelta,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    ToolCompleted,
    ToolStarted,
)
from agentd.services.chat_service import ChatService
from agentd.storage.db import Database
from agentd.storage.repositories import RunEventRepository, RunRepository
from agentd.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: 事件名映射（api-contract §3）；run.cancelled 为 M3 新增（契约只加不破）
_EVENT_NAMES: dict[type, str] = {
    RunStarted: "run.started",
    MessageDelta: "message.delta",
    ReasoningDelta: "reasoning.delta",
    ToolStarted: "tool.started",
    ToolCompleted: "tool.completed",
    MessageCompleted: "message.completed",
    RunCompleted: "run.completed",
    RunFailed: "run.failed",
}
_PERSISTED_TYPES = {
    name
    for cls, name in _EVENT_NAMES.items()
    if cls not in (MessageDelta, ReasoningDelta)
}


def serialize_event(event: RunEvent) -> tuple[str, dict[str, Any]]:
    """RunEvent → (契约事件名, payload dict)。"""
    name = _EVENT_NAMES[type(event)]
    if isinstance(event, RunStarted):
        payload: dict[str, Any] = {"run_id": event.run_id, "session_id": event.session_id}
    elif isinstance(event, (MessageDelta, ReasoningDelta)):
        payload = {"delta": event.delta}
    elif isinstance(event, ToolStarted):
        payload = {"tool_call_id": event.tool_call_id, "name": event.name, "args": event.args}
    elif isinstance(event, ToolCompleted):
        payload = {
            "tool_call_id": event.tool_call_id,
            "name": event.name,
            "status": event.status,
            "duration_ms": event.duration_ms,
        }
    elif isinstance(event, MessageCompleted):
        payload = {
            "content": event.content,
            "usage": {
                "input_tokens": event.usage.input_tokens,
                "output_tokens": event.usage.output_tokens,
            },
        }
    elif isinstance(event, RunCompleted):
        payload = {
            "run_id": "",
            "usage": {
                "input_tokens": event.usage.input_tokens,
                "output_tokens": event.usage.output_tokens,
            },
        }
    else:  # RunFailed
        payload = {
            "error": {"code": event.code, "message": event.message, "retryable": event.retryable}
        }
    return name, payload


@dataclass
class ActiveRun:
    run_id: str
    session_id: str
    task: asyncio.Task[None]
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)
    last_seq: int = 0


class RunManager:
    def __init__(
        self,
        db: Database,
        provider: Provider,
        *,
        tools: ToolRegistry | None = None,
        model: str = "unknown",
        runner_kwargs: dict[str, Any] | None = None,
        global_concurrency: int = 8,
        project_concurrency: int = 4,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tools = tools
        self.model = model
        self.project_concurrency = project_concurrency
        self.runner_kwargs = runner_kwargs or {}
        self.service = ChatService(db)
        self.events = RunEventRepository(db)
        self.runs = RunRepository(db)
        self._active: dict[str, ActiveRun] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._project_sems: dict[str, asyncio.Semaphore] = {}

    # ---------- 查询 ----------

    def get(self, run_id: str) -> ActiveRun | None:
        return self._active.get(run_id)

    async def shutdown(self) -> None:
        """进程停机：取消活跃 run（各自持久化 cancelled）并等待收尾。"""
        tasks = [active.task for active in self._active.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---------- 启动 ----------

    async def start(
        self,
        *,
        session_row: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        session_id = str(session_row["id"])
        project_id = str(session_row["project_id"])
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise AppError(ErrorCode.CONFLICT, "session 正在执行另一个 run")
        # 未锁 → 立即占用（acquire 无等待，与 locked() 检查在同一事件循环步内原子）
        await lock.acquire()
        run = await self.service.create_run(session_id, project_id=project_id, model=self.model)
        active = ActiveRun(
            run_id=str(run["id"]),
            session_id=session_id,
            task=asyncio.create_task(self._execute(run, user_input)),
        )
        self._active[active.run_id] = active
        return run

    async def _execute(self, run: dict[str, Any], user_input: str) -> None:
        run_id = str(run["id"])
        session_id = str(run["session_id"])
        project_id = str(run["project_id"])
        active = self._active.get(run_id)
        assert active is not None
        project_sem = self._project_sems.setdefault(
            project_id, asyncio.Semaphore(self.project_concurrency)
        )
        stream = None
        try:
            async with self._global_sem, project_sem:
                stream = self.service.stream_run(
                    run,
                    user_input=user_input,
                    provider=self.provider,
                    tools=self.tools,
                    runner_kwargs=self.runner_kwargs,
                )
                async for event in stream:
                    await self._emit(active, event)
        except asyncio.CancelledError:
            await self.runs.finish(run_id, "cancelled", error={"code": "cancelled"})
            await self._emit_raw(
                active, "run.cancelled", {"run_id": run_id, "reason": "cancelled"}, persist=True
            )
            logger.info("run.cancelled", extra={"run_id": run_id})
        except Exception:
            logger.exception("run.task_failed", extra={"run_id": run_id})
            await self.runs.finish(
                run_id, "failed", error={"code": "internal", "message": "run 执行异常"}
            )
            await self._emit_raw(
                active,
                "run.failed",
                {"error": {"code": "internal", "message": "run 执行异常", "retryable": False}},
                persist=True,
            )
        finally:
            if stream is not None:
                await stream.aclose()
            lock = self._session_locks.get(session_id)
            if lock is not None and lock.locked():
                lock.release()
            for queue in active.subscribers:
                await queue.put(None)
            self._active.pop(run_id, None)

    async def _emit(self, active: ActiveRun, event: RunEvent) -> None:
        name, payload = serialize_event(event)
        if isinstance(event, RunStarted):
            payload["run_id"] = active.run_id
            payload["session_id"] = active.session_id
        if isinstance(event, RunCompleted):
            payload["run_id"] = active.run_id
        await self._emit_raw(active, name, payload, persist=name in _PERSISTED_TYPES)

    async def _emit_raw(
        self, active: ActiveRun, name: str, payload: dict[str, Any], *, persist: bool
    ) -> None:
        active.last_seq += 1
        seq = active.last_seq
        if persist:
            await self.events.append(active.run_id, seq, name, payload)
        for queue in list(active.subscribers):
            await queue.put({"seq": seq, "type": name, "payload": payload})

    # ---------- 订阅 / 取消 ----------

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        active = self._active.get(run_id)
        if active is None:
            raise AppError(ErrorCode.NOT_FOUND, f"run 不在运行中：{run_id}")
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        active.subscribers.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        active = self._active.get(run_id)
        if active is not None:
            active.subscribers.discard(queue)

    async def cancel(self, run_id: str) -> dict[str, Any]:
        active = self._active.get(run_id)
        if active is None:
            row = await self.runs.get(run_id)
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND, f"run 不存在：{run_id}")
            if row["status"] in RunRepository.TERMINAL_STATUSES:
                raise AppError(ErrorCode.CONFLICT, f"run 已是终态：{row['status']}")
            raise AppError(ErrorCode.CONFLICT, f"run 不在本进程（可能已中断）：{row['status']}")
        active.task.cancel()
        return {"run_id": run_id, "status": "cancelled"}
