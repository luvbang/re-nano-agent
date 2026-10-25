"""按 Settings 构建带重试与故障切换的 provider 链（v0.2 多 provider）。

- 主 provider：llm_provider（openai | anthropic | responses），openai/responses
  共用 llm_* 凭据，anthropic 用 anthropic_* 凭据
- 备选链：llm_fallbacks（逗号分隔，与主 provider 同名去重）——主链重试耗尽后
  逐个切换（FailoverProvider），每个成员各自包 RetryingProvider
- 无任何凭据时返回 None（维持「模型未配置」语义：/v1/runs 返回 502 model_error）

向后兼容：只配 llm_api_key（不设 llm_provider/fallbacks）等价于原先的
OpenAICompatProvider + RetryingProvider。
"""

from __future__ import annotations

from agentd.config import Settings
from agentd.providers.anthropic import AnthropicProvider
from agentd.providers.base import Provider
from agentd.providers.failover import FailoverProvider
from agentd.providers.openai_compat import OpenAICompatProvider
from agentd.providers.responses import ResponsesProvider
from agentd.providers.retry import RetryingProvider

_KNOWN_KINDS = ("openai", "anthropic", "responses")


def _make_member(kind: str, settings: Settings) -> Provider | None:
    """单个 provider 成员（不带重试）；凭据缺失返回 None（跳过该成员）。"""
    if kind == "anthropic":
        api_key = settings.anthropic_api_key.get_secret_value()
        if not api_key:
            return None
        return AnthropicProvider(
            api_key=api_key,
            base_url=settings.anthropic_base_url,
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_output,
            timeout_s=settings.llm_timeout_s,
        )
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        return None
    if kind == "responses":
        return ResponsesProvider(
            api_key=api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            max_output_tokens=settings.llm_max_output,
            timeout_s=settings.llm_timeout_s,
        )
    return OpenAICompatProvider(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )


def build_provider(settings: Settings) -> tuple[Provider | None, str]:
    """返回 (provider 链 | None, run 记录用模型名)。"""
    kinds = [settings.llm_provider.strip() or "openai"]
    kinds += [s.strip() for s in settings.llm_fallbacks.split(",") if s.strip()]
    # 去重保序：主 provider 重复出现在 fallbacks 里没有意义
    seen: dict[str, None] = {}
    for kind in kinds:
        if kind in _KNOWN_KINDS:
            seen.setdefault(kind)

    members: list[Provider] = []
    for kind in seen:
        member = _make_member(kind, settings)
        if member is not None:
            members.append(RetryingProvider(member, max_retries=settings.llm_retries))
    if not members:
        return None, settings.llm_model
    primary: Provider = members[0] if len(members) == 1 else FailoverProvider(members)
    return primary, getattr(primary, "model", settings.llm_model)
