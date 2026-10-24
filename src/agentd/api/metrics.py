"""进程内指标（M5 D4）：计数器/ gauge / 直方图 + Prometheus 文本输出。

不引 prometheus-client（与 ADR-005 同思路：需求简单、零依赖、单实例内存态）。
重启清零可接受；多实例/长期存储 v0.2 换 Prometheus 抓取侧解决。
"""

from __future__ import annotations

import threading

BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

Labels = tuple[tuple[str, str], ...]


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, float]] = {}
        self._gauges: dict[str, float] = {}
        self._observations: dict[str, list[float]] = {}

    def inc(self, name: str, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0.0) + 1

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._observations.setdefault(name, []).append(value)

    def snapshot_gauge(self, name: str) -> float | None:
        with self._lock:
            return self._gauges.get(name)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                for key, value in sorted(series.items()):
                    label_str = ",".join(f'{k}="{v}"' for k, v in key)
                    suffix = "{" + label_str + "}" if label_str else ""
                    lines.append(f"{name}{suffix} {int(value)}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
            for name, values in sorted(self._observations.items()):
                lines.append(f"# TYPE {name} histogram")
                for bucket in BUCKETS:
                    count = sum(1 for v in values if v <= bucket)
                    lines.append(f'{name}_bucket{{le="{bucket}"}} {count}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {len(values)}')
                lines.append(f"{name}_sum {sum(values):.6f}")
                lines.append(f"{name}_count {len(values)}")
        return "\n".join(lines) + "\n"
