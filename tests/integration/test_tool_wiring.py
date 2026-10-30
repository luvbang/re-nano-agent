"""工具接线正确性测试（回归防线）。

背景（真实缺陷）：M2 实现了 ``WebFetchTool`` 并配齐 SSRF/pinned transport 的安全测试，
但 ``main.py`` 的装配路径从未注册它——文档对外声明「平台内置 web_fetch」，走 HTTP API
的 run 却拿不到；``ShellTool`` 也只在 ``agentd chat`` 里按开关注册，平台 API 侧永不注册。
这些测试直接断言**装配结果**（而非工具自身行为），专门守住这类"实现对了但没接线"的漂移。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.base import ToolDefinition
from agentd.providers.fake import FakeChatProvider, demo_turn
from agentd.tools.base import Tool, ToolResult
from agentd.tools.factory import build_tool_registry, platform_tools
from agentd.tools.shell import ShellTool
from agentd.tools.web import WebFetchTool

ADMIN_KEY = "admin-tool-wiring"
BASE_TOOLS = {"echo", "get_time", "read_file", "write_file", "edit_file", "list_dir"}


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path,
        log_level="WARNING",
        log_json=False,
        admin_api_key=ADMIN_KEY,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
async def shell_off_app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(tmp_path), provider=FakeChatProvider(turn_fn=demo_turn))
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def shell_on_app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    app = create_app(
        make_settings(
            tmp_path,
            run_shell_enabled=True,
            run_shell_allowlist="git,python -m pytest",
            run_shell_timeout_s=17.0,
        ),
        provider=FakeChatProvider(turn_fn=demo_turn),
    )
    async with app.router.lifespan_context(app):
        yield app


def provider_of(app: FastAPI) -> FakeChatProvider:
    """装配进 RunManager 的那个 fake provider（测试保留同一引用以观测工具清单）。"""
    manager = app.state.run_manager
    assert manager is not None
    provider = manager.provider
    assert isinstance(provider, FakeChatProvider)
    return provider


# ---------- HTTP API 侧装配（缺陷的直接回归防线） ----------


async def test_run_manager_always_registers_web_fetch(shell_off_app: FastAPI) -> None:
    """web_fetch 是内置能力，无条件注册（shell 关闭也必须存在）。"""
    manager = shell_off_app.state.run_manager
    assert manager is not None
    names = manager.tools.names()
    assert "web_fetch" in names
    assert set(names) >= BASE_TOOLS


async def test_run_manager_shell_absent_when_disabled(shell_off_app: FastAPI) -> None:
    manager = shell_off_app.state.run_manager
    assert manager is not None
    assert "shell" not in manager.tools.names()


async def test_run_manager_shell_present_when_enabled(shell_on_app: FastAPI) -> None:
    manager = shell_on_app.state.run_manager
    assert manager is not None
    assert "shell" in manager.tools.names()


async def test_api_run_exposes_web_fetch_to_model(shell_off_app: FastAPI) -> None:
    """端到端：走 HTTP API 起一个 run，provider 收到的工具清单里必须有 web_fetch。"""
    provider = provider_of(shell_off_app)
    admin = {"Authorization": f"Bearer {ADMIN_KEY}"}
    async with AsyncClient(
        transport=ASGITransport(app=shell_off_app), base_url="http://t"
    ) as client:
        project = (
            await client.post("/v1/admin/projects", json={"name": "p"}, headers=admin)
        ).json()
        key = (
            await client.post(
                "/v1/admin/keys", json={"project_id": project["id"]}, headers=admin
            )
        ).json()["key"]
        headers = {"Authorization": f"Bearer {key}"}
        session = (await client.post("/v1/sessions", json={}, headers=headers)).json()
        created = await client.post(
            f"/v1/sessions/{session['id']}/runs", json={"input": "你好"}, headers=headers
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        # run 在后台任务里跑，等终态再断言（否则模型调用可能还没发生）
        for _ in range(200):
            run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
            if run["status"] in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.02)
        assert run["status"] == "completed"
    # 首个模型调用即带全量工具定义
    requested = provider.requested_tools[0]
    assert requested is not None
    assert "web_fetch" in {definition.name for definition in requested}


# ---------- 工厂装配（两侧共用路径） ----------


def test_platform_tools_always_include_web_fetch(tmp_path: Path) -> None:
    tools = platform_tools(workspace_root=tmp_path)
    by_name = {tool.definition.name: tool for tool in tools}
    assert set(by_name) >= BASE_TOOLS | {"web_fetch"}
    assert isinstance(by_name["web_fetch"], WebFetchTool)
    assert "shell" not in by_name


def test_platform_tools_shell_carries_settings(tmp_path: Path) -> None:
    tools = platform_tools(
        workspace_root=tmp_path,
        shell_enabled=True,
        shell_allowlist="git,python -m pytest",
        shell_timeout_s=17.0,
    )
    shell = {tool.definition.name: tool for tool in tools}["shell"]
    assert isinstance(shell, ShellTool)
    assert shell.workspace_root == tmp_path
    assert shell.allowlist == ["git", "python -m pytest"]
    assert shell.timeout_s == 17.0


def test_build_tool_registry_honors_shell_flag(tmp_path: Path) -> None:
    off = build_tool_registry(make_settings(tmp_path))
    on = build_tool_registry(make_settings(tmp_path, run_shell_enabled=True))
    assert "web_fetch" in off.names() and "shell" not in off.names()
    assert "web_fetch" in on.names() and "shell" in on.names()


def test_mcp_duplicate_name_yields_to_builtin(tmp_path: Path) -> None:
    """MCP 工具与内置同名时必须「让位给内置」，不能让启动失败（docs/mcp.md 的承诺）。

    回归防线：``main.py`` 早前只有一行注释说"register 抛错则跳过"，实际没有 try，
    而 ``ToolRegistry.register`` 对重名是直接 raise——一个 MCP 服务器恰好暴露了
    ``read_file`` 之类的同名工具，整个应用就起不来。
    """
    from agentd.tools.registry import ToolRegistry

    class _Fake(Tool):
        """最小可注册工具：只为触发重名冲突。"""

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(name="read_file", description="MCP 版", parameters={})

        async def execute(self, args: dict[str, Any]) -> ToolResult:  # pragma: no cover
            return ToolResult(content="mcp")

    registry = ToolRegistry()
    registry.register_all(platform_tools(workspace_root=tmp_path))
    before = registry.names()

    # 底层契约不变：registry 本身仍对重名报错 —— 吞异常是**调用方**（main.py）的职责
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_Fake())

    # 且失败不能污染已有注册表
    assert registry.names() == before
    assert "read_file" in registry.names()

