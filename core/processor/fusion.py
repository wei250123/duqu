import math
from typing import Any, Dict, List, Optional, Callable

from core.data_types import CollectResult


class SensorFusion:
    WEIGHTED_AVG = "weighted_avg"
    KALMAN_SIMPLE = "kalman_simple"
    COMPLEMENTARY = "complementary"
    MAX_LIKELIHOOD = "max_likelihood"
    MEDIAN = "median"
    CUSTOM = "custom"

    def __init__(self):
        self._kalman_states: Dict[str, dict] = {}

    def fuse(self, results: List[CollectResult], method: str,
             params: Optional[dict] = None) -> Optional[CollectResult]:
        if not results:
            return None
        params = params or {}
        method_map = {
            SensorFusion.WEIGHTED_AVG: self._weighted_average,
            SensorFusion.KALMAN_SIMPLE: self._kalman_simple,
            SensorFusion.COMPLEMENTARY: self._complementary_filter,
            SensorFusion.MAX_LIKELIHOOD: self._max_likelihood,
            SensorFusion.MEDIAN: self._median_fusion,
        }
        handler = method_map.get(method, self._weighted_average)
        return handler(results, params)

    def _weighted_average(self, results: List[CollectResult],
                          params: dict) -> Optional[CollectResult]:
        weights = params.get('weights', [1.0] * len(results))
        total_weight = 0.0
        weighted_sum = 0.0
        for i, r in enumerate(results):
            if r.success and r.value is not None:
                w = weights[i] if i < len(weights) else 1.0
                total_weight += w
                weighted_sum += float(r.value) * w
        if total_weight == 0:
            return None
        fused_value = weighted_sum / total_weight
        base = results[0]
        return CollectResult(
            device_id=base.device_id,
            point_name=params.get('output_name', base.point_name),
            point_description=f"融合({method})",
            value=fused_value,
            raw_value=fused_value,
            unit=base.unit,
            timestamp=max(r.timestamp for r in results),
            success=True
        )

    def _median_fusion(self, results: List[CollectResult],
                       params: dict) -> Optional[CollectResult]:
        valid = [float(r.value) for r in results if r.success and r.value is not None]
        if not valid:
            return None
        valid.sort()
        n = len(valid)
        if n % 2 == 1:
            fused = valid[n // 2]
        else:
            fused = (valid[n // 2 - 1] + valid[n // 2]) / 2
        base = results[0]
        return CollectResult(
            device_id=base.device_id,
            point_name=params.get('output_name', base.point_name),
            point_description=f"融合({method})",
            value=fused, raw_value=fused,
            unit=base.unit,
            timestamp=max(r.timestamp for r in results),
            success=True
        )

    def _kalman_simple(self, results: List[CollectResult],
                       params: dict) -> Optional[CollectResult]:
        base = results[0]
        key = base.point_name
        valid_results = [r for r in results if r.success and r.value is not None]
        if not valid_results:
            return None
        state = self._kalman_states.get(key, {
            'x': float(valid_results[0].value),
            'p': 1.0
        })
        q = float(params.get('process_noise', 0.01))
        r_val = float(params.get('measurement_noise', 0.1))
        for r in valid_results:
            z = float(r.value)
            state['p'] = state['p'] + q
            k = state['p'] / (state['p'] + r_val)
            state['x'] = state['x'] + k * (z - state['x'])
            state['p'] = (1 - k) * state['p']
        self._kalman_states[key] = state
        return CollectResult(
            device_id=base.device_id,
            point_name=params.get('output_name', base.point_name),
            point_description=f"融合({method})",
            value=state['x'], raw_value=state['x'],
            unit=base.unit,
            timestamp=max(r.timestamp for r in results),
            success=True
        )

    def _complementary_filter(self, results: List[CollectResult],
                              params: dict) -> Optional[CollectResult]:
        valid = [r for r in results if r.success and r.value is not None]
        if len(valid) < 2:
            return valid[0] if valid else None
        alpha = float(params.get('alpha', 0.98))
        fused = alpha * float(valid[0].value) + (1 - alpha) * float(valid[1].value)
        base = results[0]
        return CollectResult(
            device_id=base.device_id,
            point_name=params.get('output_name', base.point_name),
            point_description=f"融合({method})",
            value=fused, raw_value=fused,
            unit=base.unit,
            timestamp=max(r.timestamp for r in results),
            success=True
        )

    def _max_likelihood(self, results: List[CollectResult],
                        params: dict) -> Optional[CollectResult]:
        valid = [float(r.value) for r in results if r.success and r.value is not None]
        if not valid:
            return None
        mean = sum(valid) / len(valid)
        variance = sum((v - mean) ** 2 for v in valid) / len(valid)
        base = results[0]
        return CollectResult(
            device_id=base.device_id,
            point_name=params.get('output_name', base.point_name),
            point_description=f"融合({method})",
            value=mean, raw_value=mean,
            unit=base.unit,
            timestamp=max(r.timestamp for r in results),
            success=True
        )

    def reset(self):
        self._kalman_states.clear()


sensor_fusion = SensorFusion()