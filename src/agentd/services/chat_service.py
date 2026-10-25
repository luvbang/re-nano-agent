"""ChatService：会话内一次 run 的编排与持久化（M2 D1）。

职责边界：
- Runner 只管对话循环与事件流（M1）；本服务负责「DB 视角的一次 run」——
  建档（queued→running）、历史装载、消息落库（经 runner.on_message）、
  终态与用量/tool_calls 落库、会话 touch。
- M3 的 runs/SSE API 直接复用本服务；取消（/cancel）进来后先关闭事件流再写 interrupted。

失败语义：run 失败（RunFailed）时 user 消息已落库（真实发生过），
assistant 不落（没有可信内容）；run 状态 failed + error_json。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from agentd.providers.base import ChatMessage, Provider
from agentd.runtime.compaction import HistoryCompactor
from agentd.runtime.events import RunCompleted, RunEvent, RunFailed, ToolCompleted, ToolStarted
from agentd.runtime.runner import AgentRunner
from agentd.services.memory import MemoryService
from agentd.services.usage_service import UsageService
from agentd.storage.db import Database
from agentd.storage.repositories import (
    MessageRepository,
    RunRepository,
    SessionRepository,
    ToolCallRepository,
    UsageRepository,
    rows_to_chat_messages,
)
from agentd.tools.registry import ToolRegistry


class ChatService:
    def __init__(
        self,
        db: Database,
        *,
        usage_service: UsageService | None = None,
        compactor: HistoryCompactor | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        self.db = db
        self.usage_service = usage_service
        self.compactor = compactor
        self.memory = memory
        self.messages = MessageRepository(db)
        self.runs = RunRepository(db)
        self.sessions = SessionRepository(db)
        self.tool_calls = ToolCallRepository(db)
        self.usage = UsageRepository(db)

    async def load_history(self, session_id: str) -> list[ChatMessage]:
        rows = await self.messages.list_for_session(session_id)
        return rows_to_chat_messages(rows)

    async def stream(
        self,
        session_id: str,
        *,
        project_id: str,
        user_input: str,
        provider: Provider,
        model: str,
        tools: ToolRegistry | None = None,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> AsyncGenerator[RunEvent, None]:
        """CLI 便捷入口：create_run + stream_run。"""
        run = await self.create_run(session_id, project_id=project_id, model=model)
        async for event in self.stream_run(
            run,
            user_input=user_input,
            provider=provider,
            tools=tools,
            runner_kwargs=runner_kwargs,
        ):
            yield event

    async def create_run(
        self, session_id: str, *, project_id: str, model: str
    ) -> dict[str, Any]:
        """建 run 档（status=queued）。API 先拿到 run_id 返回 202，再后台执行。"""
        return await self.runs.create(session_id=session_id, project_id=project_id, model=model)

    async def stream_run(
        self,
        run: dict[str, Any],
        *,
        user_input: str,
        provider: Provider,
        tools: ToolRegistry | None = None,
        runner_kwargs: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[RunEvent, None]:
        """执行既有 run（queued → running → 终态）并落库；事件流与 runner 相同。

        model：本次 run 的模型覆盖（None = provider 默认）。
        """
        session_id = str(run["session_id"])
        project_id = str(run["project_id"])
        await self.runs.set_status(str(run["id"]), "running")

        async def persist(message: ChatMessage) -> None:
            call_id = message.get("tool_call_id")
            if message["role"] == "tool" and call_id in pending_tools:
                # runner 先 notify(tool 消息) 再发 ToolCompleted，这里顺手留预览
                pending_tools[call_id]["preview"] = (message.get("content") or "")[:200]
            await self.messages.append(
                session_id,
                role=message["role"],
                text=message.get("content"),
                tool_calls=message.get("tool_calls"),
                tool_call_id=message.get("tool_call_id"),
            )

        memory_block = ""
        if self.memory is not None:
            memory_block = await self.memory.prompt_block(project_id)
        runner = AgentRunner(
            provider,
            tools=tools,
            run_id=str(run["id"]),
            session_id=session_id,
            memory_block=memory_block,
            on_message=persist,
            model=model or str(run.get("model") or "") or None,
            **(runner_kwargs or {}),
        )
        usage_in = usage_out = 0
        failure: RunFailed | None = None
        pending_tools: dict[str, dict[str, Any]] = {}

        if self.compactor is not None:
            history = await self.compactor.compact(session_id)
        else:
            history = await self.load_history(session_id)
        async for event in runner.run(history, user_input):
            if isinstance(event, ToolStarted):
                pending_tools[event.tool_call_id] = {
                    "name": event.name,
                    "args_json": json.dumps(event.args, ensure_ascii=False),
                    "preview": "",
                    "status": "error",
                    "duration_ms": 0,
                }
            elif isinstance(event, ToolCompleted):
                record = pending_tools.get(event.tool_call_id)
                if record is not None:
                    record["status"] = event.status
                    record["duration_ms"] = event.duration_ms
                    await self.tool_calls.record(
                        run_id=str(run["id"]),
                        tool_call_id=event.tool_call_id,
                        name=record["name"],
                        args_json=record["args_json"],
                        result_preview=record["preview"],
                        status=record["status"],
                        duration_ms=record["duration_ms"],
                    )
            elif isinstance(event, RunCompleted):
                usage_in = event.usage.input_tokens
                usage_out = event.usage.output_tokens
            elif isinstance(event, RunFailed):
                failure = event
            yield event

        if failure is not None:
            await self.runs.finish(
                str(run["id"]),
                "failed",
                input_tokens=usage_in,
                output_tokens=usage_out,
                error={"code": failure.code, "message": failure.message},
            )
        else:
            await self.runs.finish(
                str(run["id"]), "completed", input_tokens=usage_in, output_tokens=usage_out
            )
            usage_kwargs: dict[str, object] = {
                "project_id": project_id,
                "run_id": str(run["id"]),
                "model": str(run["model"] or "unknown"),
                "input_tokens": usage_in,
                "output_tokens": usage_out,
            }
            if self.usage_service is not None:
                await self.usage_service.record(**usage_kwargs)  # type: ignore[arg-type]
            else:
                await self.usage.record(**usage_kwargs)  # type: ignore[arg-type]
        await self.sessions.touch(session_id)
