"""令牌桶限流（M3 D3）：per-key RPM + 全局兜底，内存态（单实例）。

- 桶容量 = rate_limit_per_min，按每秒 rate/60 回填
- 超限返回需等待秒数（调用方转 429 + Retry-After）
- 无后台线程：每次 check 惰性结算（按时间差补代币）
"""

from __future__ import annotations

import time
from typing import Any


class TokenBucket:
    def __init__(self, capacity: int, refill_per_min: float) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_per_s = refill_per_min / 60.0
        self._last = time.monotonic()

    def try_acquire(self, tokens: float = 1.0) -> float | None:
        """成功返回 None；失败返回建议等待秒数。"""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self._last) * self.refill_per_s)
        self._last = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return None
        deficit = tokens - self.tokens
        return deficit / self.refill_per_s if self.refill_per_s > 0 else 60.0


class RateLimiter:
    def __init__(self, *, global_per_min: int = 240) -> None:
        self.global_bucket = TokenBucket(global_per_min, global_per_min)
        self._key_buckets: dict[str, TokenBucket] = {}

    def check(self, key_row: dict[str, Any]) -> float | None:
        """全局桶先过，再过 per-key 桶；返回 None 或等待秒数（取较大者）。"""
        global_wait = self.global_bucket.try_acquire()
        if global_wait is not None:
            return global_wait
        key_id = str(key_row["id"])
        rate = int(key_row.get("rate_limit_per_min") or 60)
        bucket = self._key_buckets.get(key_id)
        if bucket is None or bucket.capacity != rate:
            bucket = TokenBucket(rate, rate)
            self._key_buckets[key_id] = bucket
        wait = bucket.try_acquire()
        if wait is not None:
            # 全局那枚代币已扣，退回去保持公平（简化：不退还也可，这里选择退还）
            self.global_bucket.tokens = min(
                self.global_bucket.capacity, self.global_bucket.tokens + 1
            )
            return wait
        return None
