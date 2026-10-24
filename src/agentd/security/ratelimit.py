"""每 key 限流（M3）：进程内滑动窗口（RPM）。

单实例 v0.1 够用；M5 若多副本再换共享存储。返回 (是否放行, 建议重试秒数)。
"""

from __future__ import annotations

import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, window_s: float = 60.0) -> None:
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, limit_per_min: int) -> tuple[bool, float]:
        """放行则记录本次命中；超限则不记录并返回需等待的秒数。"""
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= limit_per_min:
            return False, max(self.window_s - (now - hits[0]), 0.1)
        hits.append(now)
        return True, 0.0
