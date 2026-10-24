"""本地 CLI：``python -m agentd.cli <command>``。

命令：
    migrate   应用数据库迁移（幂等）
    serve     起 uvicorn（等价于 uvicorn agentd.main:create_app --factory）
    chat      终端多轮对话（--fake 离线演示，或配置 AGENTD_LLM_* 走真实模型）
    version   打印版本与解析后的配置
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Callable

from agentd.config import APP_VERSION, Settings, get_settings
from agentd.log import configure_logging
from agentd.providers.base import Provider
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.providers.openai_compat import OpenAICompatProvider
from agentd.providers.retry import RetryingProvider
from agentd.runtime.context import ContextBuilder
from agentd.runtime.events import (
    MessageCompleted,
    MessageDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    ToolCompleted,
    ToolStarted,
)
from agentd.services.chat_service import ChatService
from agentd.storage.db import Database
from agentd.storage.repositories import ProjectRepository, SessionRepository
from agentd.tools.builtin import BUILTIN_TOOLS
from agentd.tools.filesystem import filesystem_tools
from agentd.tools.registry import ToolRegistry
from agentd.tools.shell import ShellTool


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


async def _cmd_purge(args: argparse.Namespace) -> int:
    """删除一个 project 的全部数据（级联会话/run/消息/用量；审计保留）。

    go-live 数据保留项的落地：删除前建议先跑 deploy/backup.sh。
    """
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    db = Database(
        settings.db_path or settings.data_dir / "agentd.db",
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    db.migrate()
    project_id = args.project
    project = await ProjectRepository(db).get(project_id)
    if project is None:
        print(f"project 不存在：{project_id}")
        return 1
    counts: dict[str, int] = {}
    for table, sql in (
        ("sessions", "SELECT COUNT(*) n FROM sessions WHERE project_id = ?"),
        ("runs", "SELECT COUNT(*) n FROM runs WHERE project_id = ?"),
        ("messages", "SELECT COUNT(*) n FROM messages WHERE session_id IN"
            " (SELECT id FROM sessions WHERE project_id = ?)"),
        ("usage_records", "SELECT COUNT(*) n FROM usage_records WHERE project_id = ?"),
        ("tool_calls", "SELECT COUNT(*) n FROM tool_calls WHERE run_id IN"
            " (SELECT id FROM runs WHERE project_id = ?)"),
        ("run_events", "SELECT COUNT(*) n FROM run_events WHERE run_id IN"
            " (SELECT id FROM runs WHERE project_id = ?)"),
    ):
        row = await db.fetch_one(sql, (project_id,))
        counts[table] = int(row["n"]) if row else 0
    plan = ", ".join(f"{table}={n}" for table, n in counts.items())
    if not args.yes:
        print(f"将删除 project {project_id}（{project['name']}）：{plan}")
        print("审计日志保留（project_id 置空）。确认请加 --yes；建议先跑 deploy/backup.sh。")
        return 2
    deleted = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.close()
    print(f"purged project={project_id} rows(cascaded)≈{plan} projects_deleted={deleted}")
    print("提示：workspace 目录未动（如需彻底清理请手动删除其 workspace/<project_id>）。")
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


TurnFn = Callable[[str], AsyncIterator[RunEvent]]


async def _chat_repl(
    turn: TurnFn,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> int:
    """多轮对话 REPL；turn(text) 产出一轮事件流（历史归 turn 的实现管）。

    input/print 可注入（测试与演示共用同一条路径）；返回 0。
    """
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
        usage_note = ""
        async for event in turn(line):
            if isinstance(event, MessageDelta):
                print_fn(event.delta, end="", flush=True)
            elif isinstance(event, ToolStarted):
                print_fn(f"\n[tool] {event.name} {event.args}")
            elif isinstance(event, ToolCompleted):
                print_fn(f"[tool] {event.name} {event.status} {event.duration_ms}ms")
            elif isinstance(event, MessageCompleted):
                usage_note = (
                    f"\n[usage] in={event.usage.input_tokens} out={event.usage.output_tokens}"
                )
            elif isinstance(event, RunCompleted):
                print_fn(usage_note)
            elif isinstance(event, RunFailed):
                print_fn(f"\n[failed:{event.code}] {event.message}")
        print_fn()


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
    settings.ensure_dirs()
    db = Database(
        settings.db_path or settings.data_dir / "agentd.db",
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    db.migrate()

    async def main() -> int:
        projects = ProjectRepository(db)
        sessions = SessionRepository(db)
        service = ChatService(db)
        project = await projects.get_or_create(
            name="local", workspace_path=str(settings.workspace_root)
        )
        session = await sessions.get_or_create_by_title(
            str(project["id"]), args.session, external_user_id="cli"
        )
        assert settings.workspace_root is not None  # _resolve_paths 已填充
        registry = ToolRegistry(
            tool_timeout_s=settings.run_tool_timeout_s,
            overflow_root=settings.workspace_root / ".runs",
        ).register_all(BUILTIN_TOOLS)
        registry.register_all(filesystem_tools(settings.workspace_root))
        if settings.run_shell_enabled:
            registry.register(
                ShellTool(
                    settings.workspace_root,
                    allowlist=settings.run_shell_allowlist.split(","),
                    timeout_s=settings.run_shell_timeout_s,
                )
            )
        context_builder = ContextBuilder(
            context_window=settings.llm_context_window, max_output=settings.llm_max_output
        )
        model = "fake-demo" if args.fake else (args.model or settings.llm_model)
        session_id = str(session["id"])
        project_id = str(project["id"])

        async def turn(text: str) -> AsyncIterator[RunEvent]:
            async for event in service.stream(
                session_id,
                project_id=project_id,
                user_input=text,
                provider=provider,
                model=model,
                tools=registry,
                runner_kwargs={
                    "max_iterations": settings.run_max_iterations,
                    "timeout_s": settings.run_timeout_s,
                    "context_builder": context_builder,
                },
            ):
                yield event

        print_fn: Callable[..., None] = print
        print_fn(
            f"[agentd chat] session={args.session}（已落库，重启可续聊）"
            " 工具：echo、get_time；exit 退出"
        )
        try:
            return await _chat_repl(turn)
        finally:
            db.close()

    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        print("\n(bye)")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentd", description="Agent Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="应用数据库迁移（幂等）").set_defaults(func=_cmd_migrate)

    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="开发模式热重载")
    serve.set_defaults(func=_cmd_serve)

    chat = sub.add_parser("chat", help="终端多轮对话（M1；会话持久化随 M2 落地）")
    chat.add_argument("--session", default="demo", help="会话标签（仅展示，M2 起落库）")
    chat.add_argument("--fake", action="store_true", help="离线脚本化 provider，无需 API key")
    chat.add_argument("--model", default=None, help="覆盖 AGENTD_LLM_MODEL")
    chat.set_defaults(func=_cmd_chat)

    purge = sub.add_parser(
        "purge", help="删除一个 project 的全部数据（级联；审计保留）"
    )
    purge.add_argument("--project", required=True, help="project id（p_ 开头）")
    purge.add_argument("--yes", action="store_true", help="确认执行（不加则只打印计划）")
    purge.set_defaults(func=lambda args: asyncio.run(_cmd_purge(args)))

    sub.add_parser("version", help="打印版本与配置").set_defaults(func=_cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
