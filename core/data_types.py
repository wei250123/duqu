import time
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class CollectMode(Enum):
    TIMER = "timer"
    TRIGGER = "trigger"
    MANUAL = "manual"
    CONTINUOUS = "continuous"


class DeviceStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"

@dataclass
class CollectResult:
    device_id: str
    point_name: str
    point_description: str
    value: Any
    raw_value: Any
    unit: str
    timestamp: float
    success: bool
    error_message: str = ""
    alarm_high: Optional[float] = None
    alarm_low: Optional[float] = None
    is_alarm: bool = False
    filtered_value: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'device_id': self.device_id,
            'point_name': self.point_name,
            'point_description': self.point_description,
            'value': self.value,
            'raw_value': self.raw_value,
            'unit': self.unit,
            'timestamp': self.timestamp,
            'success': self.success,
            'error_message': self.error_message,
            'is_alarm': self.is_alarm,
            'alarm_high': self.alarm_high,
            'alarm_low': self.alarm_low
        }