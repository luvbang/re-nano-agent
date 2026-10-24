"""安全测试：SSRF 判定与 web_fetch 逐跳校验（M2 D4 DoD）。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from agentd.security.ssrf import SsrfViolationError, assert_ip_public, assert_public_url
from agentd.tools.web import WebFetchTool


def resolve_to(*ips: str) -> Any:
    def resolve(host: str) -> list[str]:
        return list(ips)

    return resolve


PUBLIC = ("93.184.216.34",)  # example.com 段


def test_loopback_ip_rejected() -> None:
    for url in ("http://127.0.0.1/", "http://localhost/", "https://[::1]/"):
        with pytest.raises(SsrfViolationError):
            assert_public_url(url, resolve=resolve_to("127.0.0.1"))


def test_private_ranges_rejected() -> None:
    for ip in ("10.1.2.3", "192.168.1.1", "172.16.0.9", "169.254.169.254", "fd00::1"):
        with pytest.raises(SsrfViolationError):
            assert_ip_public(ip)


def test_metadata_ip_rejected() -> None:
    # 云元数据端点：字面 IP 与主机名两种形态
    with pytest.raises(SsrfViolationError):
        assert_public_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SsrfViolationError):
        assert_public_url(
            "http://metadata.google.internal/", resolve=resolve_to("169.254.169.254")
        )


def test_non_http_scheme_rejected() -> None:
    for url in ("file:///etc/passwd", "ftp://x/", "gopher://x/"):
        with pytest.raises(SsrfViolationError, match="http"):
            assert_public_url(url, resolve=resolve_to(*PUBLIC))


def test_hostname_resolving_to_mixed_ips_rejected() -> None:
    # 一个公网 + 一个内网 = 拒绝（DNS rebinding 常见形态）
    with pytest.raises(SsrfViolationError):
        assert_public_url("https://evil.example/", resolve=resolve_to("93.184.216.34", "10.0.0.5"))


def test_public_url_passes_and_returns_ips() -> None:
    addresses = assert_public_url("https://ok.example/x", resolve=resolve_to(*PUBLIC))
    assert addresses == ["93.184.216.34"]


def test_dns_failure_rejected() -> None:
    def fail(host: str) -> list[str]:
        raise OSError("no dns")

    with pytest.raises(SsrfViolationError, match="解析失败"):
        assert_public_url("https://nope.example/", resolve=fail)


# ---------- web_fetch 工具（validator 注入：*.example 视为公网，其余走真实判定） ----------


def fake_validator(url: str) -> list[str]:
    host = httpx.URL(url).host or ""
    if host.endswith(".example"):
        return ["93.184.216.34"]
    return assert_public_url(url)  # 字面 IP（如 192.168.0.1）会被真实拒绝


def web_tool() -> WebFetchTool:
    return WebFetchTool(validator=fake_validator)


@respx.mock
async def test_web_fetch_happy_path() -> None:
    respx.get("https://ok.example/page").mock(
        return_value=httpx.Response(200, text="页面内容", headers={"content-type": "text/html"})
    )
    tool = web_tool()
    result = await tool.execute({"url": "https://ok.example/page"})
    assert not result.is_error
    assert "页面内容" in result.content


@respx.mock
async def test_web_fetch_redirect_to_private_rejected() -> None:
    respx.get("https://ok.example/redir").mock(
        return_value=httpx.Response(302, headers={"location": "http://192.168.0.1/admin"})
    )
    tool = web_tool()
    result = await tool.execute({"url": "https://ok.example/redir"})
    assert result.is_error
    assert "拒绝" in result.content


@respx.mock
async def test_web_fetch_follows_public_redirects() -> None:
    respx.get("https://ok.example/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://ok.example/b"})
    )
    respx.get("https://ok.example/b").mock(
        return_value=httpx.Response(200, text="final", headers={"content-type": "text/plain"})
    )
    tool = web_tool()
    result = await tool.execute({"url": "https://ok.example/a"})
    assert not result.is_error and "final" in result.content


@respx.mock
async def test_web_fetch_non_text_content_rejected() -> None:
    binary = httpx.Response(
        200,
        content=b"\x00\x01",
        headers={"content-type": "application/octet-stream"},
    )
    respx.get("https://ok.example/bin").mock(return_value=binary)
    tool = web_tool()
    result = await tool.execute({"url": "https://ok.example/bin"})
    assert result.is_error and "Content-Type" in result.content


@respx.mock
async def test_web_fetch_error_status_is_error_result() -> None:
    respx.get("https://ok.example/404").mock(return_value=httpx.Response(404))
    tool = web_tool()
    result = await tool.execute({"url": "https://ok.example/404"})
    assert result.is_error and "404" in result.content
