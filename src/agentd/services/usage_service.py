"""UsageService（M4 D2）：token → 成本换算与用量记录。

价格表来自 ``AGENTD_LLM_PRICE_TABLE``（JSON：``{"模型": {"input": $/1M, "output": $/1M}}``），
未配置或模型不在表内 → 成本记 0（token 计量始终准确）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agentd.storage.db import Database
from agentd.storage.repositories import UsageRepository

logger = logging.getLogger(__name__)


def parse_price_table(raw: str) -> dict[str, dict[str, float]]:
    """解析价格表；坏 JSON 记警告并退化为空表（计量不受影响）。"""
    if not raw or not raw.strip():
        return {}
    try:
        parsed: Any = json.loads(raw)
    except ValueError:
        logger.warning("price_table.invalid_json")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("price_table.invalid_shape")
        return {}
    table: dict[str, dict[str, float]] = {}
    for model, prices in parsed.items():
        if isinstance(prices, dict):
            table[str(model)] = {
                "input": float(prices.get("input", 0) or 0),
                "output": float(prices.get("output", 0) or 0),
            }
    return table


class UsageService:
    def __init__(
        self, db: Database, price_table: dict[str, dict[str, float]] | None = None
    ) -> None:
        self.db = db
        self.repo = UsageRepository(db)
        self.price_table = price_table or {}

    def cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = self.price_table.get(model)
        if not prices:
            return 0.0
        return round(
            input_tokens / 1_000_000 * prices["input"]
            + output_tokens / 1_000_000 * prices["output"],
            6,
        )

    async def record(
        self,
        *,
        project_id: str,
        run_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        cost = self.cost_usd(model, input_tokens, output_tokens)
        await self.repo.record(
            project_id=project_id,
            run_id=run_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        await self.db.execute(
            "UPDATE runs SET cost_usd = cost_usd + ? WHERE id = ?", (cost, run_id)
        )
        return cost
