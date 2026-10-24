"""安全测试：shell 工具边界（M2 D4 DoD：默认关、allowlist、cwd、超时不悬挂）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentd.tools.shell import ShellTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


async def test_disabled_by_default(workspace: Path) -> None:
    result = await ShellTool(workspace).execute({"command": "echo hi"})
    assert result.is_error and "未启用" in result.content


async def test_command_outside_allowlist_rejected(workspace: Path) -> None:
    tool = ShellTool(workspace, allowlist=["git status"])
    result = await tool.execute({"command": "rm -rf /"})
    assert result.is_error and "allowlist" in result.content
    # 前缀匹配但更长的命令允许（git status --short）
    ok = await ShellTool(workspace, allowlist=["echo"]).execute({"command": "echo hello"})
    assert not ok.is_error and "hello" in ok.content


async def test_runs_inside_workspace_cwd(workspace: Path, tmp_path: Path) -> None:
    marker = "probe.txt"
    if sys.platform == "win32":
        command = f"echo x > {marker}"
    else:
        command = f"touch {marker}"
    tool_allow = ShellTool(workspace, allowlist=["echo", "touch"])
    result = await tool_allow.execute({"command": command})
    assert not result.is_error
    assert (workspace / marker).exists()
    assert not (tmp_path / marker).exists()  # 没有落在 workspace 外


async def test_nonzero_exit_reported_not_raised(workspace: Path) -> None:
    tool = ShellTool(workspace, allowlist=["exit"])
    result = await tool.execute({"command": "exit 3"})
    assert not result.is_error  # 命令失败是正常结果，不是工具错误
    assert "exit=3" in result.content or "exit=1" in result.content  # Windows cmd 的 exit 语义


async def test_timeout_kills_process(workspace: Path) -> None:
    if sys.platform == "win32":
        command = "ping -n 30 127.0.0.1"
        allowlist = ["ping"]
    else:
        command = "sleep 30"
        allowlist = ["sleep"]
    tool = ShellTool(workspace, allowlist=allowlist, timeout_s=0.5)
    result = await tool.execute({"command": command})
    assert result.is_error and "超时" in result.content
