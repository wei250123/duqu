import time
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

from core.data_types import CollectResult
from utils.logger import log_manager


@dataclass
class TriggerRule:
    name: str
    point_name: str
    condition: str = "gt"
    threshold: float = 0.0
    debounce_ms: int = 0
    cooldown_ms: int = 5000
    enabled: bool = True
    action: str = "log"
    action_params: dict = field(default_factory=dict)
    message: str = ""


class EventManager:
    def __init__(self):
        self._rules: Dict[str, TriggerRule] = {}
        self._last_trigger_times: Dict[str, float] = {}
        self._trigger_counts: Dict[str, int] = {}
        self._handlers: Dict[str, List[Callable]] = {}
        self._event_history: List[dict] = []

    def add_rule(self, rule: TriggerRule):
        self._rules[rule.name] = rule
        log_manager.info("事件管理器", f"添加触发规则: {rule.name}")

    def remove_rule(self, name: str):
        self._rules.pop(name, None)

    def get_rules(self) -> List[TriggerRule]:
        return list(self._rules.values())

    def register_handler(self, action_name: str, handler: Callable):
        if action_name not in self._handlers:
            self._handlers[action_name] = []
        self._handlers[action_name].append(handler)

    def process_result(self, result: CollectResult) -> List[dict]:
        events = []
        if not result.success or result.value is None:
            return events
        for rule_name, rule in self._rules.items():
            if not rule.enabled:
                continue
            if rule.point_name and rule.point_name != result.point_name:
                continue
            try:
                event = self._evaluate_rule(rule, result)
                if event:
                    events.append(event)
                    self._fire_event(event)
            except Exception as e:
                log_manager.error("事件管理器", f"规则评估异常 [{rule_name}]: {e}")
        return events

    def _evaluate_rule(self, rule: TriggerRule,
                       result: CollectResult) -> Optional[dict]:
        now = time.time()
        if not self._check_condition(rule.condition, result.value, rule.threshold):
            return None
        if rule.debounce_ms > 0:
            last_time = self._last_trigger_times.get(rule.name, 0)
            if (now - last_time) * 1000 < rule.debounce_ms:
                return None
        last_trigger = self._last_trigger_times.get(rule.name, 0)
        if rule.cooldown_ms > 0:
            if (now - last_trigger) * 1000 < rule.cooldown_ms:
                return None
        self._last_trigger_times[rule.name] = now
        self._trigger_counts[rule.name] = self._trigger_counts.get(rule.name, 0) + 1
        event = {
            'rule_name': rule.name,
            'timestamp': now,
            'device_id': result.device_id,
            'point_name': result.point_name,
            'value': result.value,
            'unit': result.unit,
            'condition': rule.condition,
            'threshold': rule.threshold,
            'action': rule.action,
            'message': rule.message.format(
                point=result.point_name,
                value=result.value,
                unit=result.unit,
                threshold=rule.threshold
            ) if rule.message else f"{result.point_name}={result.value}{result.unit} 触发规则",
            'count': self._trigger_counts[rule.name],
        }
        self._record_event(event)
        return event

    def _check_condition(self, condition: str, value: Any,
                         threshold: float) -> bool:
        v = float(value)
        conditions = {
            'gt': v > threshold,
            'gte': v >= threshold,
            'lt': v < threshold,
            'lte': v <= threshold,
            'eq': v == threshold,
            'neq': v != threshold,
            'between': threshold <= v <= (threshold + abs(threshold) * 0.1),
            'outside': v < threshold or v > threshold * 2,
            'zero': v == 0,
            'nonzero': v != 0,
            'positive': v > 0,
            'negative': v < 0,
            'always': True,
        }
        return conditions.get(condition, False)

    def _fire_event(self, event: dict):
        action = event.get('action', 'log')
        handlers = self._handlers.get(action, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log_manager.error("事件管理器", f"事件处理回调异常: {e}")
        handlers = self._handlers.get('*', [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                pass

    def _record_event(self, event: dict):
        self._event_history.append(event)
        if len(self._event_history) > 10000:
            self._event_history = self._event_history[-5000:]

    def get_history(self, limit: int = 100) -> List[dict]:
        return self._event_history[-limit:]

    def get_stats(self) -> dict:
        return {
            'total_events': len(self._event_history),
            'rule_counts': dict(self._trigger_counts),
            'last_triggers': dict(self._last_trigger_times),
        }

    def clear_history(self):
        self._event_history.clear()
        self._trigger_counts.clear()
        self._last_trigger_times.clear()


event_manager = EventManager()