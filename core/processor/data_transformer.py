import time
import json
from typing import Dict, Any, List, Optional

from core.data_types import CollectResult
from utils.helpers import format_timestamp


class DataTransformer:
    def __init__(self, device_id: str = "", topic_prefix: str = "factory/line1"):
        self._device_id = device_id
        self._topic_prefix = topic_prefix
        self._timestamp_format = '%Y-%m-%d %H:%M:%S.%f'

    def set_topic_prefix(self, prefix: str):
        self._topic_prefix = prefix

    def set_device_id(self, device_id: str):
        self._device_id = device_id

    def transform_single(self, result: CollectResult) -> Dict[str, Any]:
        return {
            'device_id': result.device_id or self._device_id,
            'point_name': result.point_name,
            'value': result.value,
            'unit': result.unit,
            'timestamp': format_timestamp(time.localtime(result.timestamp)
                                          if isinstance(result.timestamp, float)
                                          else result.timestamp, self._timestamp_format),
            'success': result.success,
            'is_alarm': result.is_alarm,
            'error_message': result.error_message
        }

    def transform_batch(self, results: List[CollectResult]) -> Dict[str, Any]:
        timestamp = format_timestamp(None, self._timestamp_format)
        values = {}
        alarms = []
        for result in results:
            values[result.point_name] = {
                'value': result.value,
                'unit': result.unit,
                'success': result.success,
                'is_alarm': result.is_alarm
            }
            if result.is_alarm:
                alarms.append({
                    'point_name': result.point_name,
                    'value': result.value,
                    'unit': result.unit,
                    'alarm_high': result.alarm_high,
                    'alarm_low': result.alarm_low
                })
        return {
            'device_id': self._device_id,
            'timestamp': timestamp,
            'values': values,
            'alarms': alarms,
            'stats': {
                'total': len(results),
                'success': sum(1 for r in results if r.success),
                'fail': sum(1 for r in results if not r.success)
            }
        }

    def get_topic(self, device_id: str = "", data_type: str = "telemetry",
                  point_name: str = "") -> str:
        did = device_id or self._device_id
        parts = [self._topic_prefix]
        if did:
            parts.append(did)
        parts.append(data_type)
        if point_name:
            parts.append(point_name)
        return '/'.join(parts)

    def to_json(self, data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)


class AlarmChecker:
    def __init__(self):
        self._alarm_history: List[Dict[str, Any]] = []

    def check(self, result: CollectResult) -> Optional[Dict[str, Any]]:
        if not result.success or result.value is None:
            return None
        is_high = result.alarm_high is not None and result.value > result.alarm_high
        is_low = result.alarm_low is not None and result.value < result.alarm_low
        if is_high or is_low:
            alarm = {
                'timestamp': time.time(),
                'device_id': result.device_id,
                'point_name': result.point_name,
                'value': result.value,
                'unit': result.unit,
                'type': 'high' if is_high else 'low',
                'threshold': result.alarm_high if is_high else result.alarm_low,
                'description': result.point_description
            }
            self._alarm_history.append(alarm)
            if len(self._alarm_history) > 10000:
                self._alarm_history = self._alarm_history[-5000:]
            return alarm
        return None

    def get_recent_alarms(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._alarm_history[-limit:]

    def clear_history(self):
        self._alarm_history.clear()

    def get_alarm_count(self) -> int:
        return len(self._alarm_history)