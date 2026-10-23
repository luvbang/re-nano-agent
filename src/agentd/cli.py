"""本地 CLI：``python -m agentd.cli <command>``。

命令：
    migrate   应用数据库迁移（幂等）
    serve     起 uvicorn（等价于 uvicorn agentd.main:create_app --factory）
    version   打印版本与解析后的配置
"""

from __future__ import annotations

import argparse
import sys

from agentd.config import APP_VERSION, get_settings
from agentd.log import configure_logging
from agentd.storage.db import Database


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentd", description="Agent Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="应用数据库迁移（幂等）").set_defaults(func=_cmd_migrate)

    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="开发模式热重载")
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser("version", help="打印版本与配置").set_defaults(func=_cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
