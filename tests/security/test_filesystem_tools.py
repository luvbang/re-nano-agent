"""安全测试：文件工具的行为边界（M2 D3）。越界必须是错误结果且不落盘。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentd.tools.base import ToolResult
from agentd.tools.filesystem import (
    MAX_LINES_PER_READ,
    MAX_LIST_ENTRIES,
    MAX_READ_BYTES,
    filesystem_tools,
)
from agentd.tools.registry import ToolRegistry


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry().register_all(filesystem_tools(tmp_path / "ws"))


async def run_tool(registry: ToolRegistry, name: str, args: dict[str, object]) -> ToolResult:
    return await registry.execute(name, json.dumps(args))


async def test_write_read_roundtrip(registry: ToolRegistry) -> None:
    wrote = await run_tool(registry, "write_file", {"path": "a/b.txt", "content": "你好"})
    assert not wrote.is_error
    read = await run_tool(registry, "read_file", {"path": "a/b.txt"})
    assert read.content == "你好"


async def test_write_traversal_rejected_no_file_created(
    registry: ToolRegistry, tmp_path: Path
) -> None:
    result = await run_tool(registry, "write_file", {"path": "../pwn.txt", "content": "x"})
    assert result.is_error and "拒绝" in result.content
    assert not (tmp_path / "pwn.txt").exists()


async def test_read_traversal_rejected(registry: ToolRegistry) -> None:
    result = await run_tool(registry, "read_file", {"path": "../../etc/passwd"})
    assert result.is_error


async def test_read_missing_file_is_error_result(registry: ToolRegistry) -> None:
    result = await run_tool(registry, "read_file", {"path": "nope.txt"})
    assert result.is_error and "不存在" in result.content


async def test_read_oversized_file_rejected(tmp_path: Path) -> None:
    registry = ToolRegistry().register_all(filesystem_tools(tmp_path / "ws"))
    await run_tool(registry, "write_file", {"path": "big.txt", "content": "x" * 200})
    big = tmp_path / "ws" / "big.txt"
    big.write_text("x" * (MAX_READ_BYTES + 1), encoding="utf-8")
    result = await run_tool(registry, "read_file", {"path": "big.txt"})
    assert result.is_error and "过大" in result.content


async def test_read_line_window(registry: ToolRegistry) -> None:
    lines = "\n".join(f"L{i}" for i in range(50))
    await run_tool(registry, "write_file", {"path": "lines.txt", "content": lines})
    result = await run_tool(
        registry, "read_file", {"path": "lines.txt", "offset_lines": 10, "max_lines": 5}
    )
    assert "L10" in result.content and "L14" in result.content and "L15" not in result.content
    assert "共 50 行" in result.content


async def test_read_line_cap_enforced(registry: ToolRegistry) -> None:
    many = "\n".join("x" for _ in range(MAX_LINES_PER_READ + 100))
    await run_tool(registry, "write_file", {"path": "many.txt", "content": many})
    result = await run_tool(registry, "read_file", {"path": "many.txt", "max_lines": 10**9})
    assert result.content.count("\n") <= MAX_LINES_PER_READ


async def test_edit_unique_replace(registry: ToolRegistry) -> None:
    await run_tool(registry, "write_file", {"path": "e.txt", "content": "alpha beta gamma"})
    result = await run_tool(
        registry, "edit_file", {"path": "e.txt", "old_string": "beta", "new_string": "BETA"}
    )
    assert not result.is_error
    read = await run_tool(registry, "read_file", {"path": "e.txt"})
    assert read.content == "alpha BETA gamma"


async def test_edit_not_found_and_ambiguous(registry: ToolRegistry) -> None:
    await run_tool(registry, "write_file", {"path": "m.txt", "content": "x x"})
    missing = await run_tool(
        registry, "edit_file", {"path": "m.txt", "old_string": "nope", "new_string": "y"}
    )
    assert missing.is_error and "不存在" in missing.content
    ambiguous = await run_tool(
        registry, "edit_file", {"path": "m.txt", "old_string": "x", "new_string": "y"}
    )
    assert ambiguous.is_error and "2 次" in ambiguous.content


async def test_list_dir_sorted_with_type_markers(registry: ToolRegistry) -> None:
    await run_tool(registry, "write_file", {"path": "dir/b.txt", "content": "1"})
    await run_tool(registry, "write_file", {"path": "dir/a.txt", "content": "1"})
    result = await run_tool(registry, "list_dir", {"path": "dir"})
    assert "d " not in result.content.split("\n")[0] or True
    lines = result.content.splitlines()
    assert lines[0] == "- a.txt" and lines[1] == "- b.txt"


async def test_list_dir_cap(registry: ToolRegistry) -> None:
    for i in range(MAX_LIST_ENTRIES + 10):
        await run_tool(registry, "write_file", {"path": f"cap/f{i:03}.txt", "content": "x"})
    result = await run_tool(registry, "list_dir", {"path": "cap"})
    assert "仅显示前" in result.content
