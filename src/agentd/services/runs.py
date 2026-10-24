"""RunService（M3）：run 的生命周期编排。

- create_run：冲突检查（同 session 只允许一个活跃 run）→ 落库 queued → 起后台任务
- _execute：加载历史（M2 ConversationService）→ AgentRunner 流式消费 →
  事件编 seq、控制类事件落 run_events（delta 不落库，契约 §3）→ 广播给订阅者 →
  终态收敛 run 行 + usage_records + 成功轮落库 messages
- 取消：task.cancel()，CancelledError 里收敛为 cancelled（SSE 以关流表达，不发事件）
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from agentd.api.errors import AppError, ErrorCode
from agentd.config import Settings
from agentd.providers.base import Provider, Usage
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
from agentd.runtime.runner import AgentRunner
from agentd.services.conversation import ConversationService
from agentd.storage.db import Database
from agentd.storage.repositories import RunRepository, SessionRepository
from agentd.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: 控制类事件（落库回放）；delta 类只广播不落库
_DELTA_TYPES = ("message.delta", "reasoning.delta")


def event_to_envelope(event: RunEvent, seq: int) -> dict[str, Any]:
    base: dict[str, Any] = {"seq": seq}
    match event:
        case RunStarted():
            return base | {
                "type": "run.started",
                "run_id": event.run_id,
                "session_id": event.session_id,
            }
        case MessageDelta():
            return base | {"type": "message.delta", "delta": event.delta}
        case ReasoningDelta():
            return base | {"type": "reasoning.delta", "delta": event.delta}
        case ToolStarted():
            return base | {
                "type": "tool.started",
                "tool_call_id": event.tool_call_id,
                "name": event.name,
                "args": event.args,
            }
        case ToolCompleted():
            return base | {
                "type": "tool.completed",
                "tool_call_id": event.tool_call_id,
                "name": event.name,
                "status": event.status,
                "duration_ms": event.duration_ms,
            }
        case MessageCompleted():
            return base | {
                "type": "message.completed",
                "content": event.content,
                "usage": {
                    "input_tokens": event.usage.input_tokens,
                    "output_tokens": event.usage.output_tokens,
                },
            }
        case RunCompleted():
            return base | {
                "type": "run.completed",
                "usage": {
                    "input_tokens": event.usage.input_tokens,
                    "output_tokens": event.usage.output_tokens,
                },
            }
        case RunFailed():
            return base | {
                "type": "run.failed",
                "error": {
                    "code": event.code,
                    "message": event.message,
                    "retryable": event.retryable,
                },
            }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class RunService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.runs = RunRepository(db)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}

    # ---------- 对外 ----------

    async def create_run(
        self,
        *,
        session: dict[str, Any],
        input: str,
        provider: Provider,
        tools: ToolRegistry | None,
        settings: Settings,
    ) -> dict[str, Any]:
        active = await self.db.fetch_one(
            "SELECT id FROM runs WHERE session_id = ? AND status IN ('queued', 'running')",
            (session["id"],),
        )
        if active is not None:
            raise AppError(ErrorCode.CONFLICT, "该会话已有进行中的 run")
        run = await self.runs.create(
            session_id=str(session["id"]),
            project_id=str(session["project_id"]),
            model=settings.llm_model,
        )
        task = asyncio.create_task(
            self._execute(
                run_id=str(run["id"]),
                session=session,
                input=input,
                provider=provider,
                tools=tools,
                settings=settings,
            )
        )
        self._tasks[str(run["id"])] = task
        return run

    async def cancel(self, run_id: str) -> dict[str, Any]:
        run = await self.runs.get(run_id)
        if run is None:
            raise AppError(ErrorCode.NOT_FOUND, "run 不存在")
        if run["status"] in RunRepository.TERMINAL_STATUSES:
            return run
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            # 等终态收敛（cancel 路径的 DB 写很快；asyncio.wait 不传播 CancelledError）
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait({task}, timeout=5.0)
        return await self.runs.get(run_id)  # type: ignore[return-value]

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._subscribers.get(run_id, set()).discard(queue)

    async def replay(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            "SELECT payload_json FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            parsed = json.loads(row["payload_json"])
            if isinstance(parsed, dict):
                events.append(parsed)
        return events

    async def shutdown(self) -> None:
        """进程收尾：取消所有进行中的任务（下次启动由 recover_interrupted 收敛）。"""
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    # ---------- 内部 ----------

    async def _execute(
        self,
        *,
        run_id: str,
        session: dict[str, Any],
        input: str,
        provider: Provider,
        tools: ToolRegistry | None,
        settings: Settings,
    ) -> None:
        session_id = str(session["id"])
        project_id = str(session["project_id"])
        conversation = ConversationService(self.db, token_budget=settings.context_token_budget)
        usage_total = Usage()
        error_body: dict[str, Any] | None = None
        final_status = "completed"
        runner: AgentRunner | None = None
        try:
            history = await conversation.load_history(session_id)
            runner = AgentRunner(
                provider,
                tools=tools,
                run_id=run_id,
                session_id=session_id,
                max_iterations=settings.run_max_iterations,
                timeout_s=settings.run_timeout_s,
            )
            await self.runs.set_status(run_id, "running")
            seq = 0
            async for event in runner.run(history, input):
                seq += 1
                envelope = event_to_envelope(event, seq)
                if envelope["type"] not in _DELTA_TYPES:
                    await self._persist_event(run_id, envelope)
                self._publish(run_id, envelope)
                match event:
                    case RunCompleted():
                        usage_total = event.usage
                    case RunFailed():
                        error_body = envelope["error"]
                        final_status = "failed"
        except asyncio.CancelledError:
            final_status = "cancelled"
            try:
                await self._finalize(
                    run_id=run_id, status="cancelled", usage=usage_total, error=None,
                    project_id=project_id, model=settings.llm_model,
                )
            except asyncio.CancelledError:
                pass  # 重复取消：状态由下次启动 recover_interrupted 兜底
        except Exception:
            logger.exception("run.execute_failed", extra={"run_id": run_id})
            final_status = "failed"
            error_body = {"code": "internal", "message": "run 执行异常", "retryable": False}
            await self._publish_and_persist_failure(run_id, error_body)
            await self._finalize(
                run_id=run_id, status="failed", usage=usage_total, error=error_body,
                project_id=project_id, model=settings.llm_model,
            )
        else:
            await self._finalize(
                run_id=run_id, status=final_status, usage=usage_total, error=error_body,
                project_id=project_id, model=settings.llm_model,
            )
            if runner is not None and runner.last_exchange and final_status == "completed":
                await conversation.persist_exchange(session_id, runner.last_exchange)
                await SessionRepository(self.db).touch(session_id)
        finally:
            self._close(run_id)

    async def _persist_event(self, run_id: str, envelope: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json) VALUES (?, ?, ?, ?)",
            (run_id, int(envelope["seq"]), str(envelope["type"]),
             json.dumps(envelope, ensure_ascii=False)),
        )

    async def _publish_and_persist_failure(
        self, run_id: str, error_body: dict[str, Any]
    ) -> None:
        row = await self.db.fetch_one("SELECT COALESCE(MAX(seq), 0) AS m FROM run_events WHERE run_id = ?", (run_id,))
        seq = int(row["m"]) + 1 if row else 1
        envelope = {"seq": seq, "type": "run.failed", "error": error_body}
        await self._persist_event(run_id, envelope)
        self._publish(run_id, envelope)

    async def _finalize(
        self,
        *,
        run_id: str,
        status: str,
        usage: Usage,
        error: dict[str, Any] | None,
        project_id: str,
        model: str,
    ) -> None:
        await self.runs.set_status(run_id, status)
        await self.db.execute(
            "UPDATE runs SET input_tokens = ?, output_tokens = ?, error_json = ?,"
            " finished_at = ? WHERE id = ?",
            (
                usage.input_tokens,
                usage.output_tokens,
                json.dumps(error, ensure_ascii=False) if error else None,
                _now_iso(),
                run_id,
            ),
        )
        if status == "completed":
            # usage_records：计量与 /v1/usage 聚合的数据源（cost v0.1 恒 0）
            await self.db.execute(
                "INSERT INTO usage_records (id, project_id, run_id, model, input_tokens,"
                " output_tokens) VALUES (?, ?, ?, ?, ?, ?)",
                (f"u_{run_id[2:]}", project_id, run_id, model,
                 usage.input_tokens, usage.output_tokens),
            )

    def _publish(self, run_id: str, envelope: dict[str, Any]) -> None:
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(envelope)

    def _close(self, run_id: str) -> None:
        for queue in self._subscribers.pop(run_id, set()):
            queue.put_nowait(None)  # 关流哨兵：订阅侧据此结束 SSE
        self._tasks.pop(run_id, None)
