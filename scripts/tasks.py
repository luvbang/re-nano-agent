#!/usr/bin/env python
"""跨平台任务运行器：Makefile 的等价实现（Windows 无 make / 无 gh 时使用）。

用法：
    uv run python scripts/tasks.py check
    uv run python scripts/tasks.py dev

任务：install / migrate / dev / serve / test / lint / type / check / docker-build / up / down / tag
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence

PY = sys.executable


def _run(cmd: Sequence[str]) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, check=False).returncode


def _chain(*groups: Sequence[str]) -> int:
    for cmd in groups:
        code = _run(cmd)
        if code != 0:
            return code
    return 0


def install() -> int:
    return _run(["uv", "sync", "--all-groups"])


def migrate() -> int:
    return _run([PY, "-m", "agentd.cli", "migrate"])


def dev() -> int:
    return _run([PY, "-m", "agentd.cli", "serve", "--reload"])


def serve() -> int:
    return _run([PY, "-m", "agentd.cli", "serve"])


def test() -> int:
    return _run([PY, "-m", "pytest"])


def lint() -> int:
    return _run([PY, "-m", "ruff", "check", "."])


def typecheck() -> int:
    return _run([PY, "-m", "mypy"])


def check() -> int:
    return _chain(lint_cmd(), type_cmd(), test_cmd())


def lint_cmd() -> list[str]:
    return [PY, "-m", "ruff", "check", "."]


def type_cmd() -> list[str]:
    return [PY, "-m", "mypy"]


def test_cmd() -> list[str]:
    return [PY, "-m", "pytest"]


def _docker() -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("docker CLI not found in PATH")
    return docker


def docker_build() -> int:
    return _run([_docker(), "compose", "build"])


def up() -> int:
    return _run([_docker(), "compose", "up", "-d", "--build"])


def down() -> int:
    return _run([_docker(), "compose", "down"])


def tag() -> int:
    version = sys.argv[2] if len(sys.argv) > 2 else "v0.1.0-m0"
    return _run(["git", "tag", "-a", version, "-m", version])


TASKS: dict[str, Callable[[], int]] = {
    "install": install,
    "migrate": migrate,
    "dev": dev,
    "serve": serve,
    "test": test,
    "lint": lint,
    "type": typecheck,
    "check": check,
    "docker-build": docker_build,
    "up": up,
    "down": down,
    "tag": tag,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        print(__doc__)
        return 0 if len(argv) > 1 else 2
    task = TASKS.get(argv[1])
    if task is None:
        print(f"unknown task: {argv[1]}\navailable: {', '.join(TASKS)}", file=sys.stderr)
        return 2
    sys.argv = [argv[0], *argv[1:]]
    return task()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
