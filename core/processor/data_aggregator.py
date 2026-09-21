import time
from typing import List, Dict, Any, Optional
from collections import defaultdict

from config.config_manager import DataAggregateConfig
from core.data_types import CollectResult


class DataAggregator:
    def __init__(self, config: DataAggregateConfig):
        self._config = config
        self._window_data: Dict[str, List[float]] = defaultdict(list)
        self._window_start: Optional[float] = None

    @property
    def config(self) -> DataAggregateConfig:
        return self._config

    @config.setter
    def config(self, value: DataAggregateConfig):
        self._config = value

    def feed(self, result: CollectResult) -> Optional[CollectResult]:
        if not self._config.enabled:
            return result
        now = time.time()
        if self._window_start is None:
            self._window_start = now
        if now - self._window_start >= self._config.window_seconds:
            aggregated = self._aggregate_and_reset(now)
            if aggregated:
                return aggregated
        if result.value is not None:
            try:
                self._window_data[result.point_name].append(float(result.value))
            except (ValueError, TypeError):
                pass
        return None

    def flush(self) -> List[CollectResult]:
        results = []
        for point_name, values in self._window_data.items():
            if values:
                result = self._compute_aggregate(point_name, values, time.time())
                if result:
                    results.append(result)
        self._window_data.clear()
        self._window_start = None
        return results

    def _aggregate_and_reset(self, now: float) -> Optional[CollectResult]:
        if not self._window_data:
            self._window_start = now
            return None
        results = []
        for point_name, values in self._window_data.items():
            if values:
                result = self._compute_aggregate(point_name, values, now)
                if result:
                    results.append(result)
        self._window_data.clear()
        self._window_start = now
        return results[0] if results else None

    def _compute_aggregate(self, point_name: str, values: List[float],
                           timestamp: float) -> Optional[CollectResult]:
        if not values:
            return None
        agg_value = 0
        method = self._config.methods[0] if self._config.methods else "avg"
        if method == "avg":
            agg_value = sum(values) / len(values)
        elif method == "max":
            agg_value = max(values)
        elif method == "min":
            agg_value = min(values)
        elif method == "sum":
            agg_value = sum(values)
        elif method == "last":
            agg_value = values[-1]
        elif method == "first":
            agg_value = values[0]
        return CollectResult(
            device_id="",
            point_name=point_name,
            point_description="",
            value=agg_value,
            raw_value=agg_value,
            unit="",
            timestamp=timestamp,
            success=True
        )

    def reset(self):
        self._window_data.clear()
        self._window_start = None