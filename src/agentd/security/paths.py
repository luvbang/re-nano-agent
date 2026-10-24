"""Workspace 路径解析（M2 D3）：所有文件类工具的路径都必须过这里。

双保险：
1. ``resolve()`` 后必须仍在 workspace 内 —— 挡住 ``..``、嵌套逃逸、指向外部的软链
2. 逐段 ``is_symlink()`` 检查 —— 即使软链目标仍在 workspace 内也拒绝（行为可预测）

信任模型（SECURITY 前提）：单管理员自托管，这里防的是**模型失控/提示注入**，
不是恶意本地用户。TOCTOU（检查后替换软链）不在 v0.1 威胁模型内。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class PathOutsideWorkspaceError(Exception):
    """路径越界/含软链/非相对 —— 调用方应转为工具错误结果，绝不落盘。"""


class WorkspacePathResolver:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str) -> Path:
        """把 workspace 相对路径解析为绝对路径；任何越界迹象抛 PathOutsideWorkspaceError。"""
        raw = (relative or "").strip().replace("\\", "/")
        if not raw:
            raise PathOutsideWorkspaceError("路径为空")
        candidate = Path(raw)
        if candidate.is_absolute() or raw.startswith("/"):
            raise PathOutsideWorkspaceError(f"只接受相对路径：{relative!r}")
        parts = PurePosixPath(raw).parts  # "." / ".." 的 parts 为空
        if parts and ":" in parts[0]:
            # Windows 盘符（C:）与流语法都按绝对路径处理
            raise PathOutsideWorkspaceError(f"只接受相对路径：{relative!r}")
        # 逐段检查软链（含中间目录），目标即使仍在 workspace 内也拒绝
        current = self.root
        for segment in PurePosixPath(raw).parts:
            if segment in (".", ".."):
                continue  # resolve 阶段统一判定
            current = current / segment
            if current.is_symlink():
                raise PathOutsideWorkspaceError(f"路径含符号链接，已拒绝：{relative!r}")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise PathOutsideWorkspaceError(f"路径越出 workspace：{relative!r}")
        return resolved
