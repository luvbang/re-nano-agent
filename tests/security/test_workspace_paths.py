"""安全测试：workspace 路径 containment（M2 D3 DoD 的一部分）。

全部用例必须通过且在 CI 阻塞（ROADMAP §7）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agentd.security.paths import PathOutsideWorkspaceError, WorkspacePathResolver


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "file.txt").write_text("inside", encoding="utf-8")
    return root


def test_relative_inside_ok(workspace: Path) -> None:
    resolver = WorkspacePathResolver(workspace)
    resolved = resolver.resolve("sub/file.txt")
    assert resolved == (workspace / "sub" / "file.txt").resolve()
    assert resolver.resolve(".") == workspace.resolve()


def test_parent_traversal_rejected(workspace: Path) -> None:
    resolver = WorkspacePathResolver(workspace)
    for bad in ("../secret", "sub/../../secret", "a/../../../etc/passwd", ".."):
        with pytest.raises(PathOutsideWorkspaceError):
            resolver.resolve(bad)


def test_absolute_paths_rejected(workspace: Path, tmp_path: Path) -> None:
    resolver = WorkspacePathResolver(workspace)
    absolute = (
        "C:/Windows/system32/config"
        if sys.platform == "win32"
        else "/etc/passwd"
    )
    for bad in (absolute, "\\server\\share", "C:\\x"):
        with pytest.raises(PathOutsideWorkspaceError):
            resolver.resolve(bad)
    assert tmp_path.is_absolute()  # 佐证：平台绝对路径形态已覆盖


def test_drive_letter_and_stream_syntax_rejected(workspace: Path) -> None:
    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(PathOutsideWorkspaceError):
        resolver.resolve("C:file.txt")
    with pytest.raises(PathOutsideWorkspaceError):
        resolver.resolve("")


def _skip_if_no_symlink_support() -> None:
    try:
        os.symlink("nonexistent-link-probe-target", "nonexistent-link-probe-link")
        os.unlink("nonexistent-link-probe-link")
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持符号链接")


def test_symlink_escaping_workspace_rejected(workspace: Path, tmp_path: Path) -> None:
    _skip_if_no_symlink_support()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, workspace / "escape.txt")
    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(PathOutsideWorkspaceError, match="符号链接"):
        resolver.resolve("escape.txt")


def test_symlink_inside_workspace_also_rejected(workspace: Path) -> None:
    _skip_if_no_symlink_support()
    os.symlink(workspace / "sub", workspace / "alias")
    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(PathOutsideWorkspaceError, match="符号链接"):
        resolver.resolve("alias/file.txt")


def test_intermediate_directory_symlink_rejected(workspace: Path, tmp_path: Path) -> None:
    _skip_if_no_symlink_support()
    os.symlink(tmp_path, workspace / "hop")
    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(PathOutsideWorkspaceError, match="符号链接"):
        resolver.resolve("hop/anything")


def test_backslash_normalized_not_an_escape(workspace: Path) -> None:
    resolver = WorkspacePathResolver(workspace)
    resolved = resolver.resolve("sub\\file.txt")  # 模型给出 Windows 风格分隔符
    assert resolved.name == "file.txt"
