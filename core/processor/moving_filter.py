"""滑动滤波模块 - 支持多种滑动窗口滤波算法"""

from collections import deque
from typing import Any, Optional

import numpy as np


class MovingFilter:
    SMA = "sma"
    EMA = "ema"
    MEDIAN = "median"

    def __init__(self, window_size: int = 10, filter_type: str = "sma",
                 alpha: float = 0.3):
        self._window_size = max(2, window_size)
        self._filter_type = filter_type
        self._alpha = max(0.01, min(0.99, alpha))
        self._buffer: deque[float] = deque(maxlen=self._window_size)
        self._ema_value: Optional[float] = None
        self._raw_history: deque[float] = deque(maxlen=self._window_size)

    @property
    def window_size(self) -> int:
        return self._window_size

    @window_size.setter
    def window_size(self, value: int):
        new_size = max(2, value)
        if new_size != self._window_size:
            self._window_size = new_size
            self._buffer = deque(self._buffer, maxlen=new_size)
            self._raw_history = deque(self._raw_history, maxlen=new_size)
            self._ema_value = None

    @property
    def filter_type(self) -> str:
        return self._filter_type

    @filter_type.setter
    def filter_type(self, value: str):
        self._filter_type = value
        self._ema_value = None

    @property
    def alpha(self) -> float:
        return self._alpha

    @alpha.setter
    def alpha(self, value: float):
        self._alpha = max(0.01, min(0.99, value))
        self._ema_value = None

    def feed(self, raw_value: Any) -> Optional[float]:
        try:
            val = float(raw_value)
        except (TypeError, ValueError):
            return None
        self._raw_history.append(val)
        self._buffer.append(val)
        if len(self._buffer) < 2:
            return val
        filtered = self._apply_filter()
        return filtered

    def reset(self):
        self._buffer.clear()
        self._raw_history.clear()
        self._ema_value = None

    @property
    def raw_values(self) -> list[float]:
        return list(self._raw_history)

    @property
    def filtered_values(self) -> list[Optional[float]]:
        return self._compute_all_filtered()

    def _compute_all_filtered(self) -> list[Optional[float]]:
        if not self._raw_history:
            return []
        raw = list(self._raw_history)
        results = [raw[0]]
        buf = deque([raw[0]], maxlen=self._window_size)
        ema = raw[0] if self._filter_type == self.EMA else None
        for v in raw[1:]:
            buf.append(v)
            if len(buf) < 2:
                results.append(v)
                continue
            if self._filter_type == self.SMA:
                results.append(sum(buf) / len(buf))
            elif self._filter_type == self.MEDIAN:
                results.append(float(np.median(list(buf))))
            elif self._filter_type == self.EMA:
                ema = self._alpha * v + (1 - self._alpha) * (ema or v)
                results.append(ema)
            else:
                results.append(v)
        return results

    def _apply_filter(self) -> float:
        if self._filter_type == self.SMA:
            return sum(self._buffer) / len(self._buffer)
        if self._filter_type == self.MEDIAN:
            return float(np.median(list(self._buffer)))
        if self._filter_type == self.EMA:
            latest = self._buffer[-1]
            if self._ema_value is None:
                self._ema_value = sum(self._buffer) / len(self._buffer)
            else:
                self._ema_value = self._alpha * latest + (1 - self._alpha) * self._ema_value
            return self._ema_value
        return self._buffer[-1]


class FilterBank:
    def __init__(self, window_size: int = 10, filter_type: str = "sma", alpha: float = 0.3):
        self._config = {
            "window_size": window_size,
            "filter_type": filter_type,
            "alpha": alpha,
        }
        self._filters: dict[str, MovingFilter] = {}

    @property
    def config(self) -> dict:
        return self._config

    def update_config(self, window_size: int = None, filter_type: str = None,
                      alpha: float = None):
        if window_size is not None:
            self._config["window_size"] = max(2, window_size)
        if filter_type is not None:
            self._config["filter_type"] = filter_type
        if alpha is not None:
            self._config["alpha"] = max(0.01, min(0.99, alpha))
        for f in self._filters.values():
            f.window_size = self._config["window_size"]
            f.filter_type = self._config["filter_type"]
            f.alpha = self._config["alpha"]

    def feed(self, point_name: str, raw_value: Any) -> Optional[float]:
        if point_name not in self._filters:
            self._filters[point_name] = MovingFilter(
                window_size=self._config["window_size"],
                filter_type=self._config["filter_type"],
                alpha=self._config["alpha"],
            )
        return self._filters[point_name].feed(raw_value)

    def get_filter(self, point_name: str) -> Optional[MovingFilter]:
        return self._filters.get(point_name)

    def reset(self, point_name: str = None):
        if point_name:
            f = self._filters.get(point_name)
            if f:
                f.reset()
        else:
            for f in self._filters.values():
                f.reset()

    def reset_all(self):
        self._filters.clear()