"""SSRF 防护（M2 D4）：工具发起的一切出站 HTTP 必须过这里。

规则：
- 仅 http/https
- 主机为字面 IP 或 DNS 解析出的**每一个**地址都必须是公网单播地址
  （回环/私网/链路本地/保留段/云元数据 169.254.169.254 全部拒绝）
- DNS 解析函数可注入（测试与未来 pinned transport 用）

已知残余风险（写入对外文档）：解析校验与实际连接之间存在 DNS rebinding 窗口。
v0.1 的信任模型是"防模型失控抓内网"，不是对抗实时 rebind 攻击；
逐跳重定向校验（tools/web.py）保证不绕行。传输层 pin 到 v0.2。
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

ResolveFn = Callable[[str], list[str]]


class SsrfViolationError(Exception):
    """URL 不允许出站：调用方转为工具错误结果。"""


_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),      # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),        # 回环
    ipaddress.ip_network("169.254.0.0/16"),     # 链路本地（含云元数据 169.254.169.254）
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),      # 基准测试段
    ipaddress.ip_network("224.0.0.0/4"),        # 组播
    ipaddress.ip_network("240.0.0.0/4"),        # 保留
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),           # ULA
    ipaddress.ip_network("fe80::/10"),          # 链路本地 v6
)


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return sorted({str(info[4][0]) for info in infos})


def assert_ip_public(ip_text: str) -> None:
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError as exc:
        raise SsrfViolationError(f"非法 IP：{ip_text!r}") from exc
    if address.is_global is False:
        raise SsrfViolationError(f"非公网地址被拒绝：{ip_text}")
    for network in _PRIVATE_NETWORKS:
        if address in network:
            raise SsrfViolationError(f"内网/保留地址段被拒绝：{ip_text}")


def assert_public_url(url: str, *, resolve: ResolveFn = _default_resolve) -> list[str]:
    """校验出站 URL；返回解析出的 IP 列表（供日志/审计）。任何不满足即抛 SsrfViolationError。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SsrfViolationError(f"仅允许 http/https：{url!r}")
    host = parts.hostname
    if not host:
        raise SsrfViolationError(f"URL 缺少主机名：{url!r}")
    # 字面 IP 直接判；主机名则要求解析出的每个地址都是公网
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        assert_ip_public(host)
        return [host]
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise SsrfViolationError(f"域名解析失败：{host}") from exc
    if not addresses:
        raise SsrfViolationError(f"域名未解析出任何地址：{host}")
    for address in addresses:
        assert_ip_public(address)
    return list(addresses)


def public_ips_only(addresses: Iterable[str]) -> bool:
    """批量判定的辅助（测试用）：全部公网返回 True。"""
    try:
        for address in addresses:
            assert_ip_public(address)
    except SsrfViolationError:
        return False
    return True
