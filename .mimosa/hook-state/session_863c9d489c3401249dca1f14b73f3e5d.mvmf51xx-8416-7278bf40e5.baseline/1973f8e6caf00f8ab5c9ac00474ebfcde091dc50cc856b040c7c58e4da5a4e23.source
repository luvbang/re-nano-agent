"""SSRF 边界（M2 D3）：web_fetch 出网前的目标校验。

策略：DNS 解析出的**所有**地址都必须是公网地址，任一命中内网/保留段即整体拒绝
（覆盖 DNS 多记录混排）。校验发生在每次 HTTP 跳转之前，重定向也不例外。

已知限制（登记为技术债，不修）：校验与实际连接之间存在 TOCTOU 窗口，严格做法是
pin 解析 IP 连接 + Host 头还原；v0.1 单管理员场景接受该窗口。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], Awaitable[list[str]]]


class SsrfBlockedError(ValueError):
    """目标地址命中内网/保留段或主机名无法解析；消息面向模型。"""


def assert_public_addresses(ips: list[str], *, host: str = "") -> None:
    for raw in ips:
        ip = ipaddress.ip_address(raw)
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 绕过手法
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SsrfBlockedError(f"目标 {host or raw} 解析到内网/保留地址，已拒绝")


async def resolve_dns(host: str) -> list[str]:
    def _resolve() -> list[str]:
        return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]

    try:
        return await asyncio.to_thread(_resolve)
    except socket.gaierror as exc:
        raise SsrfBlockedError(f"主机 {host} 无法解析：{exc}") from exc


async def assert_url_allowed(url: str, *, resolver: Resolver = resolve_dns) -> str:
    """校验单个 URL：仅 http(s)、主机为公网地址；返回规范化的 host（测试断言用）。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SsrfBlockedError(f"仅支持 http/https，收到：{parts.scheme or '(空)'}")
    host = parts.hostname
    if not host:
        raise SsrfBlockedError("URL 缺少主机名")
    # 字面量 IP 直接判定，无需 DNS
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ips = await resolver(host)
    else:
        ips = [host.strip("[]")]
    assert_public_addresses(ips, host=host)
    return host
