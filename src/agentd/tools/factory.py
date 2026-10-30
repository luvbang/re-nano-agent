"""工具装配工厂：``main.py``（HTTP API 侧）与 ``cli.py``（``agentd chat``）共用的唯一装配路径。

存在理由（真实缺陷的回归防线）：M2 实现 ``WebFetchTool`` 并配齐 SSRF/pinned transport
的安全测试，但 ``main.py`` 从未注册它——文档（README/faq/quickstart/sdk-guide）对外声明
「平台内置 web_fetch」，走 HTTP API 的 run 却拿不到该工具；``ShellTool`` 也只在 CLI 侧按
开关注册，平台 API 侧永不注册。两侧各自拼装工具列表就会这样漂移，故收口到此。
"""

from __future__ import annotations

from pathlib import Path

from agentd.config import Settings
from agentd.tools.base import Tool
from agentd.tools.builtin import BUILTIN_TOOLS
from agentd.tools.filesystem import filesystem_tools
from agentd.tools.registry import ToolRegistry
from agentd.tools.shell import ShellTool
from agentd.tools.web import WebFetchTool


def platform_tools(
    *,
    workspace_root: Path,
    shell_enabled: bool = False,
    shell_allowlist: str = "",
    shell_timeout_s: float = 30.0,
) -> tuple[Tool, ...]:
    """平台内置工具集合（不含 MCP）。

    组成：echo/get_time → 文件四件套（锁定 workspace）→ web_fetch（始终启用，纯出站只读，
    SSRF 校验与 pinned transport 在 ``WebFetchTool.execute`` 内部逐跳完成，无需外部依赖）→
    shell（仅 ``shell_enabled`` 时，allowlist 为空即拒绝一切命令）。
    """
    tools: list[Tool] = [*BUILTIN_TOOLS, *filesystem_tools(workspace_root)]
    tools.append(WebFetchTool())
    if shell_enabled:
        tools.append(
            ShellTool(
                workspace_root,
                allowlist=shell_allowlist.split(","),
                timeout_s=shell_timeout_s,
            )
        )
    return tuple(tools)


def build_tool_registry(settings: Settings) -> ToolRegistry:
    """按 settings 装配注册表：超时/溢出根目录 + 内置工具集。

    MCP 工具由调用方（``main.py``）异步加载后追加——CLI chat 不挂 MCP，保持零网络启动。
    """
    workspace_root = settings.workspace_root
    assert workspace_root is not None  # Settings 构造期已解析
    return ToolRegistry(
        tool_timeout_s=settings.run_tool_timeout_s,
        overflow_root=workspace_root / ".runs",
    ).register_all(
        platform_tools(
            workspace_root=workspace_root,
            shell_enabled=settings.run_shell_enabled,
            shell_allowlist=settings.run_shell_allowlist,
            shell_timeout_s=settings.run_shell_timeout_s,
        )
    )
