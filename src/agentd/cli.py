"""本地 CLI：``python -m agentd.cli <command>``。

命令：
    migrate   应用数据库迁移（幂等）
    serve     起 uvicorn（等价于 uvicorn agentd.main:create_app --factory）
    chat      终端多轮对话（--fake 离线演示；会话按 --session 标签落库，重启续聊）
    version   打印版本与解析后的配置
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agentd.config import APP_VERSION, Settings, get_settings
from agentd.log import configure_logging
from agentd.providers.base import ChatMessage, Provider
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.providers.openai_compat import OpenAICompatProvider
from agentd.providers.retry import RetryingProvider
from agentd.runtime.events import (
    MessageCompleted,
    MessageDelta,
    RunCompleted,
    RunFailed,
    ToolCompleted,
    ToolStarted,
)
from agentd.runtime.runner import AgentRunner
from agentd.services.conversation import ConversationService
from agentd.storage.db import Database
from agentd.storage.repositories import ProjectRepository, SessionRepository
from agentd.tools import build_workspace_tools
from agentd.tools.registry import ToolRegistry


def _cmd_migrate(_: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    settings.ensure_dirs()
    db = Database(settings.db_path or settings.data_dir / "agentd.db",
                  busy_timeout_ms=settings.sqlite_busy_timeout_ms)
    applied = db.migrate()
    versions = db.applied_versions()
    db.close()
    print(f"applied={applied or 'none'} schema_versions={versions} db={settings.db_path}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "agentd.main:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_config=None,  # 统一走 agentd.log 的 JSON 输出
        access_log=False,  # 访问日志由 RequestIDMiddleware 输出（带 request_id，不重复）
    )
    return 0


def _cmd_version(_: argparse.Namespace) -> int:
    settings = get_settings()
    print(
        f"agentd {APP_VERSION} env={settings.env} db={settings.db_path} "
        f"workspace={settings.workspace_root}"
    )
    return 0


def _build_chat_provider(args: argparse.Namespace, settings: Settings) -> Provider | None:
    if args.fake:
        return FakeChatProvider(turn_fn=demo_turn)
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        return None
    inner = OpenAICompatProvider(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=args.model or settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )
    return RetryingProvider(inner, max_retries=settings.llm_retries)


async def _chat_repl(
    runner: AgentRunner,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
    history: list[ChatMessage] | None = None,
    on_turn: Callable[[list[ChatMessage]], Awaitable[None]] | None = None,
) -> int:
    """多轮对话 REPL；input/print 可注入（测试与演示共用同一条路径）。

    history 传入初始历史（DB 加载）；on_turn 在每轮成功后收到完整交换
    （user + assistant/tool 消息），由调用方落库。失败的轮次不写回历史。
    返回 0。
    """
    history = history if history is not None else []
    tools_note = "、".join(runner.tools.names()) if runner.tools else "（无）"
    print_fn(f"[agentd chat] 工具：{tools_note}；输入 exit 退出（Ctrl+C 中断会话）")
    while True:
        try:
            line = input_fn("\nyou> ").strip()
        except EOFError:
            print_fn()
            return 0
        if not line:
            continue
        if line in {"exit", "quit"}:
            return 0
        final: str | None = None
        usage_note = ""
        async for event in runner.run(history, line):
            if isinstance(event, MessageDelta):
                print_fn(event.delta, end="", flush=True)
            elif isinstance(event, ToolStarted):
                print_fn(f"\n[tool] {event.name} {event.args}")
            elif isinstance(event, ToolCompleted):
                print_fn(f"[tool] {event.name} {event.status} {event.duration_ms}ms")
            elif isinstance(event, MessageCompleted):
                final = event.content
                usage_note = (
                    f"\n[usage] in={event.usage.input_tokens} out={event.usage.output_tokens}"
                )
            elif isinstance(event, RunCompleted):
                print_fn(usage_note)
            elif isinstance(event, RunFailed):
                print_fn(f"\n[failed:{event.code}] {event.message}")
        print_fn()
        if final is not None and runner.last_exchange:
            history.extend(runner.last_exchange)
            if on_turn is not None:
                await on_turn(runner.last_exchange)


async def _open_cli_session(
    db: Database, settings: Settings, label: str
) -> tuple[dict[str, Any], list[ChatMessage], ConversationService]:
    """打开（或创建）CLI 标签对应的会话并加载历史；默认项目 workspace 指向配置根。"""
    projects = ProjectRepository(db)
    project = await projects.get_by_name("default")
    if project is None:
        workspace = Path(settings.workspace_root or settings.data_dir / "workspace")
        project = await projects.create(name="default", workspace_path=str(workspace))
    sessions = SessionRepository(db)
    existing = await sessions.list_by_project(project["id"], limit=100)
    mine = [row for row in existing if row["external_user_id"] == "cli" and row["title"] == label]
    if mine:
        session = mine[0]
    else:
        session = await sessions.create(
            project_id=project["id"], external_user_id="cli", title=label
        )
    conversation = ConversationService(db, token_budget=settings.context_token_budget)
    history = await conversation.load_history(session["id"])
    return session, history, conversation


def _cmd_chat(args: argparse.Namespace) -> int:
    import asyncio

    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    provider = _build_chat_provider(args, settings)
    if provider is None:
        print(
            "缺少模型配置：设置 AGENTD_LLM_API_KEY / AGENTD_LLM_BASE_URL / AGENTD_LLM_MODEL，"
            "或先用 --fake 离线体验。",
            file=sys.stderr,
        )
        return 2
    db = Database(settings.db_path or settings.data_dir / "agentd.db",
                  busy_timeout_ms=settings.sqlite_busy_timeout_ms)
    db.migrate()
    registry = ToolRegistry(tool_timeout_s=settings.run_tool_timeout_s).register_all(
        build_workspace_tools(
            Path(settings.workspace_root or settings.data_dir / "workspace"),
            enable_shell=settings.enable_shell_tool,
            web_fetch=settings.web_fetch_enabled,
        )
    )

    async def amain() -> int:
        session, history, conversation = await _open_cli_session(db, settings, args.session)
        print(f"[agentd chat] session={session['id']} 已载入 {len(history)} 条历史消息")

        async def persist(exchange: list[ChatMessage]) -> None:
            await conversation.persist_exchange(session["id"], exchange)

        runner = AgentRunner(
            provider,
            tools=registry,
            run_id=f"r_cli_{args.session}",
            session_id=session["id"],
            max_iterations=settings.run_max_iterations,
            timeout_s=settings.run_timeout_s,
        )
        return await _chat_repl(runner, history=history, on_turn=persist)

    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        print("\n(bye)")
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentd", description="Agent Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="应用数据库迁移（幂等）").set_defaults(func=_cmd_migrate)

    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="开发模式热重载")
    serve.set_defaults(func=_cmd_serve)

    chat = sub.add_parser("chat", help="终端多轮对话（会话按 --session 标签落库，重启续聊）")
    chat.add_argument("--session", default="demo", help="会话标签（同一标签续聊同一会话）")
    chat.add_argument("--fake", action="store_true", help="离线脚本化 provider，无需 API key")
    chat.add_argument("--model", default=None, help="覆盖 AGENTD_LLM_MODEL")
    chat.set_defaults(func=_cmd_chat)

    sub.add_parser("version", help="打印版本与配置").set_defaults(func=_cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
