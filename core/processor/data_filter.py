from typing import Optional, Any

from config.config_manager import DataFilterConfig, config_manager
from core.data_types import CollectResult


class DataFilter:
    def __init__(self, config: DataFilterConfig):
        self._config = config
        self._last_values: dict[str, Any] = {}

    @property
    def config(self) -> DataFilterConfig:
        return self._config

    @config.setter
    def config(self, value: DataFilterConfig):
        self._config = value

    def should_upload(self, result: CollectResult) -> bool:
        if not config_manager.app_config.enable_filter:
            return True
        if self._config.enable_null_filter and result.value is None:
            return False
        if self._config.enable_threshold:
            ft = getattr(result, 'filter_threshold', None)
            if ft is not None and result.value is not None:
                if abs(result.value) > ft:
                    return True
                return False
        if self._config.enable_change_rate:
            last = self._last_values.get(result.point_name)
            if last is not None and result.value is not None and last != 0:
                change = abs((result.value - last) / last) * 100
                if change < self._config.change_rate_percent:
                    return False
        self._last_values[result.point_name] = result.value
        return True

    def filter_results(self, results: list[CollectResult]) -> list[CollectResult]:
        return [r for r in results if self.should_upload(r)]

    def reset(self):
        self._last_values.clear()