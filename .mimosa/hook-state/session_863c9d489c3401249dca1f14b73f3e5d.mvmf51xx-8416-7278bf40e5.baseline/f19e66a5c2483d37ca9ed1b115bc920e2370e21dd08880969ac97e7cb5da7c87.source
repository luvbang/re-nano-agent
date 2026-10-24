"""Workspace 路径边界（M2 D3）：所有文件工具的用户路径必须先过这里。

拒绝面（均有单测覆盖）：
- 绝对路径（Windows 盘符 / UNC、POSIX /）
- 显式 ``..`` 段（在 resolve 之前先拒绝，错误信息更可读）
- resolve 后落到 workspace 之外的目标（软链逃逸、盘符相对路径 ``C:foo``）
- NUL 等控制字符

TOCTOU 说明：resolve(strict=False) 只校验执行瞬间已存在的软链；单管理员自托管
场景下模型无法并发改写文件系统，v0.1 接受该窗口（docs/DECISIONS.md ADR-005 同思路）。
"""

from __future__ import annotations

from pathlib import Path, PurePath


class PathOutsideWorkspace(ValueError):
    """用户路径解析后不在 workspace 内；消息面向模型，不泄漏服务器绝对路径。"""


def resolve_in_workspace(workspace: Path, user_path: str) -> Path:
    """把用户提供的相对路径解析为 workspace 内的绝对路径，越界即抛错。"""
    if not user_path or not user_path.strip():
        raise PathOutsideWorkspace("path 不能为空")
    if "\x00" in user_path:
        raise PathOutsideWorkspace("path 含非法字符")
    candidate = PurePath(user_path)
    if candidate.is_absolute() or candidate.root:
        # Windows 上 "/etc/passwd"（有根无盘符）不算 is_absolute，同样必须拒绝
        raise PathOutsideWorkspace("只允许 workspace 内的相对路径")
    if ".." in candidate.parts:
        raise PathOutsideWorkspace("path 不允许包含 ..")
    root = workspace.resolve()
    target = (root / user_path).resolve(strict=False)
    if target != root and root not in target.parents:
        raise PathOutsideWorkspace(f"path 解析后超出 workspace：{user_path}")
    return target
