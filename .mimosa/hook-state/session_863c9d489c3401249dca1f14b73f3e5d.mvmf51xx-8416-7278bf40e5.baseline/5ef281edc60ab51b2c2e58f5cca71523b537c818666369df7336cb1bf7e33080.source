"""token 估算（M1 D3）：tiktoken 优先，不可用（离线拉不到 BPE / 未安装）退化为字符数/4。

估算用于上下文预算与展示（M2 ContextBuilder 的输入），不参与计费——计费一律用
Provider 回报的 usage。encoder 惰性加载并缓存，加载失败永久走 fallback，避免
每次调用都撞一次网络。
"""

from __future__ import annotations

from typing import Any

_ENCODER: Any = None
_ENCODER_LOADED = False


def _load_encoder() -> Any:
    global _ENCODER, _ENCODER_LOADED
    if not _ENCODER_LOADED:
        _ENCODER_LOADED = True
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None  # 网络受限拉不到 BPE 文件，或 tiktoken 未安装
    return _ENCODER


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = _load_encoder()
    if encoder is not None:
        return len(encoder.encode_ordinary(text))
    return max(1, (len(text) + 3) // 4)


def reset_cache_for_tests() -> None:
    """测试钩子：清除 encoder 缓存以验证两条路径。"""
    global _ENCODER, _ENCODER_LOADED
    _ENCODER = None
    _ENCODER_LOADED = False
