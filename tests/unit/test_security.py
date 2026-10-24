"""路径与 SSRF 边界测试（M2 DoD：安全测试全绿）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentd.security.paths import PathOutsideWorkspace, resolve_in_workspace
from agentd.security.ssrf import (
    SsrfBlockedError,
    assert_public_addresses,
    assert_url_allowed,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("hello", encoding="utf-8")
    return tmp_path


class TestPathGuard:
    def test_normal_relative_path(self, workspace: Path) -> None:
        target = resolve_in_workspace(workspace, "docs/a.txt")
        assert target == workspace.resolve() / "docs" / "a.txt"

    def test_nested_missing_path_allowed_for_write(self, workspace: Path) -> None:
        target = resolve_in_workspace(workspace, "new/dir/file.txt")
        assert workspace.resolve() in target.parents

    def test_reject_empty(self, workspace: Path) -> None:
        with pytest.raises(PathOutsideWorkspace, match="不能为空"):
            resolve_in_workspace(workspace, "")

    def test_reject_nul_byte(self, workspace: Path) -> None:
        with pytest.raises(PathOutsideWorkspace, match="非法字符"):
            resolve_in_workspace(workspace, "a\x00b")

    def test_reject_parent_traversal(self, workspace: Path) -> None:
        with pytest.raises(PathOutsideWorkspace, match=r"\.\."):
            resolve_in_workspace(workspace, "docs/../../secret.txt")

    def test_reject_absolute_posix(self, workspace: Path) -> None:
        with pytest.raises(PathOutsideWorkspace, match="相对路径"):
            resolve_in_workspace(workspace, "/etc/passwd")

    @pytest.mark.skipif(sys.platform != "win32", reason="盘符语义仅 Windows 成立")
    def test_reject_absolute_windows_drive(self, workspace: Path) -> None:
        with pytest.raises(PathOutsideWorkspace, match="相对路径"):
            resolve_in_workspace(workspace, "C:\\Windows\\system32")

    def test_reject_symlink_escape(self, workspace: Path) -> None:
        outside = workspace.parent / "outside_secret.txt"
        outside.write_text("secret", encoding="utf-8")
        link = workspace / "link"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"当前环境无法创建软链：{exc}")
        with pytest.raises(PathOutsideWorkspace, match="超出 workspace"):
            resolve_in_workspace(workspace, "link")


class TestSsrf:
    @pytest.mark.parametrize(
        "ips",
        [
            ["127.0.0.1"],
            ["10.0.0.5"],
            ["192.168.1.1"],
            ["172.16.0.9"],
            ["169.254.169.254"],  # 云元数据
            ["0.0.0.0"],
            ["224.0.0.1"],
            ["::1"],
            ["fd00::1"],
            ["::ffff:10.0.0.1"],  # IPv4-mapped 绕过
        ],
    )
    def test_blocked_addresses(self, ips: list[str]) -> None:
        with pytest.raises(SsrfBlockedError):
            assert_public_addresses(ips)

    def test_public_addresses_pass(self) -> None:
        assert_public_addresses(["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])

    async def test_url_rejects_scheme(self) -> None:
        with pytest.raises(SsrfBlockedError, match="http/https"):
            await assert_url_allowed("file:///etc/passwd")

    async def test_url_literal_private_ip_rejected_without_dns(self) -> None:
        with pytest.raises(SsrfBlockedError, match="内网"):
            await assert_url_allowed("http://127.0.0.1:8080/")

    async def test_url_hostname_resolved_and_checked(self) -> None:
        async def resolver(host: str) -> list[str]:
            return ["93.184.216.34"] if host == "example.com" else ["10.0.0.1"]

        host = await assert_url_allowed("https://example.com/x", resolver=resolver)
        assert host == "example.com"
        with pytest.raises(SsrfBlockedError):
            await assert_url_allowed("https://evil.example/x", resolver=resolver)

    async def test_url_mixed_records_blocked(self) -> None:
        async def resolver(host: str) -> list[str]:
            return ["93.184.216.34", "192.168.0.1"]  # 公网 + 内网混排

        with pytest.raises(SsrfBlockedError):
            await assert_url_allowed("http://mixed.test/", resolver=resolver)
