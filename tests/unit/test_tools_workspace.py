"""文件 / shell / web 工具测试（M2 D3）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from agentd.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from agentd.tools.shell import RunCommandTool
from agentd.tools.web import WebFetchTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("你好，世界", encoding="utf-8")
    return tmp_path


class TestReadFile:
    async def test_read_utf8(self, workspace: Path) -> None:
        result = await ReadFileTool(workspace).execute({"path": "docs/a.txt"})
        assert not result.is_error
        assert result.content == "你好，世界"

    async def test_missing_file_is_error_result(self, workspace: Path) -> None:
        result = await ReadFileTool(workspace).execute({"path": "nope.txt"})
        assert result.is_error and "不存在" in result.content

    async def test_dir_hint_to_list_dir(self, workspace: Path) -> None:
        result = await ReadFileTool(workspace).execute({"path": "docs"})
        assert result.is_error and "list_dir" in result.content

    async def test_traversal_rejected(self, workspace: Path) -> None:
        result = await ReadFileTool(workspace).execute({"path": "../outside.txt"})
        assert result.is_error and ".." in result.content

    async def test_truncated_at_cap(self, workspace: Path) -> None:
        (workspace / "big.txt").write_text("x" * 300_000, encoding="utf-8")
        result = await ReadFileTool(workspace).execute({"path": "big.txt"})
        assert not result.is_error
        assert "truncated at" in result.content


class TestWriteFile:
    async def test_write_creates_parents(self, workspace: Path) -> None:
        result = await WriteFileTool(workspace).execute(
            {"path": "new/deep/file.txt", "content": "data"}
        )
        assert not result.is_error
        assert (workspace / "new" / "deep" / "file.txt").read_text(encoding="utf-8") == "data"

    async def test_overwrite_existing(self, workspace: Path) -> None:
        await WriteFileTool(workspace).execute({"path": "docs/a.txt", "content": "覆盖"})
        assert (workspace / "docs" / "a.txt").read_text(encoding="utf-8") == "覆盖"

    async def test_reject_root_itself(self, workspace: Path) -> None:
        result = await WriteFileTool(workspace).execute({"path": "", "content": "x"})
        assert result.is_error

    async def test_reject_oversize(self, workspace: Path) -> None:
        result = await WriteFileTool(workspace).execute(
            {"path": "big.txt", "content": "x" * 300_000}
        )
        assert result.is_error and "上限" in result.content


class TestListDir:
    async def test_list_root(self, workspace: Path) -> None:
        result = await ListDirTool(workspace).execute({})
        assert not result.is_error
        entry = json.loads(result.content)
        assert entry == {"name": "docs", "type": "dir", "size": ""}

    async def test_list_subdir(self, workspace: Path) -> None:
        result = await ListDirTool(workspace).execute({"path": "docs"})
        entry = json.loads(result.content)
        assert entry == {"name": "a.txt", "type": "file", "size": len("你好，世界".encode())}

    async def test_empty_dir(self, workspace: Path) -> None:
        (workspace / "empty").mkdir()
        result = await ListDirTool(workspace).execute({"path": "empty"})
        assert result.content == "(empty dir)"


class TestRunCommand:
    async def test_echo_command(self, workspace: Path) -> None:
        result = await RunCommandTool(workspace).execute({"command": "echo hi_from_shell"})
        assert not result.is_error
        assert "exit=0" in result.content and "hi_from_shell" in result.content

    async def test_timeout_kills(self, workspace: Path) -> None:
        result = await RunCommandTool(workspace).execute(
            {"command": "ping -n 30 127.0.0.1 > NUL" if workspace.drive else "sleep 30",
             "timeout_s": 1}
        )
        assert result.is_error and "终止" in result.content

    async def test_nonzero_exit_is_error_result(self, workspace: Path) -> None:
        result = await RunCommandTool(workspace).execute(
            {"command": "exit 7" if workspace.drive else "sh -c 'exit 7'"}
        )
        assert result.is_error
        assert "exit=7" in result.content


_PUBLIC_RESOLVER: dict[str, list[str]] = {"example.com": ["93.184.216.34"]}


async def _public_resolver(host: str) -> list[str]:
    return _PUBLIC_RESOLVER.get(host, ["93.184.216.34"])


class TestWebFetch:
    def _tool(self) -> WebFetchTool:
        return WebFetchTool(resolver=_public_resolver, max_bytes=1_000)

    @respx.mock
    async def test_fetch_text(self) -> None:
        respx.get("https://example.com/page").mock(return_value=Response(200, text="<html>hi"))
        result = await self._tool().execute({"url": "https://example.com/page"})
        assert not result.is_error
        assert "status=200" in result.content and "hi" in result.content

    @respx.mock
    async def test_redirect_each_hop_checked(self) -> None:
        respx.get("https://example.com/start").mock(
            return_value=Response(302, headers={"Location": "http://192.168.0.1/admin"})
        )
        result = await self._tool().execute({"url": "https://example.com/start"})
        assert result.is_error and "内网" in result.content

    @respx.mock
    async def test_binary_content_rejected(self) -> None:
        respx.get("https://example.com/img").mock(
            return_value=Response(200, content=b"\x89PNG", headers={"Content-Type": "image/png"})
        )
        result = await self._tool().execute({"url": "https://example.com/img"})
        assert result.is_error and "内容类型" in result.content

    async def test_literal_private_ip_rejected_offline(self) -> None:
        result = await self._tool().execute({"url": "http://169.254.169.254/latest/meta-data"})
        assert result.is_error and "内网" in result.content
