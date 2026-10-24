"""token 估算测试（M1 D3）：tiktoken 优先、离线 fallback、缓存只加载一次。"""

from __future__ import annotations

from typing import Any

import agentd.runtime.tokens as tokens


def test_fallback_math_when_encoder_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr(tokens, "_load_encoder", lambda: None)
    assert tokens.estimate_tokens("") == 0
    assert tokens.estimate_tokens("abcd") == 1
    assert tokens.estimate_tokens("abcde") == 2
    assert tokens.estimate_tokens("x" * 400) == 100


def test_encoder_cache_flag_set_after_first_call(monkeypatch: Any) -> None:
    tokens.reset_cache_for_tests()
    assert tokens._ENCODER_LOADED is False
    tokens.estimate_tokens("hello")
    assert tokens._ENCODER_LOADED is True  # 之后重复调用不会再次尝试加载


def test_real_path_returns_positive() -> None:
    tokens.reset_cache_for_tests()
    # tiktoken 可用与否取决于环境（离线时自动 fallback），两条路径都应给出正数
    assert tokens.estimate_tokens("你好，世界 hello world") > 0
    assert tokens.estimate_tokens("a" * 1000) >= 100
