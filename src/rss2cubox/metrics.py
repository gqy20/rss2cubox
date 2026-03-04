from __future__ import annotations

import math


def percentile_ms(values: list[int], p: float) -> int:
    if not values:
        return 0
    arr = sorted(values)
    rank = max(1, math.ceil(len(arr) * p)) - 1
    rank = min(rank, len(arr) - 1)
    return int(arr[rank])


class StageMetrics:
    def __init__(self) -> None:
        self._data: dict[str, list[int]] = {}

    def observe(self, stage: str, duration_ms: int) -> None:
        self._data.setdefault(stage, []).append(max(0, int(duration_ms)))

    def total_ms(self, stage: str) -> int:
        return sum(self._data.get(stage, []))

    def p95_ms(self, stage: str) -> int:
        return percentile_ms(self._data.get(stage, []), 0.95)

    def count(self, stage: str) -> int:
        return len(self._data.get(stage, []))

    def snapshot(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for stage in ("fetch", "ai", "push"):
            out[stage] = {
                "count": self.count(stage),
                "total_ms": self.total_ms(stage),
                "p95_ms": self.p95_ms(stage),
            }
        return out
