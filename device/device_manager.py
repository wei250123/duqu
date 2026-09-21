import time
import threading
import json
from typing import List, Dict, Optional, Callable, Any
from enum import Enum

from config.config_manager import config_manager, DeviceConfig
from core.collector.collector import collector_manager
from core.data_types import DeviceStatus, CollectResult
from core.communication.serial_client import serial_manager
from core.communication.ethernet_client import ethernet_manager
from core.mqtt.mqtt_client import mqtt_manager
from core.processor.data_filter import DataFilter
from core.processor.data_aggregator import DataAggregator
from core.processor.data_transformer import DataTransformer, AlarmChecker
from core.storage.database import db
from core.storage.cache_manager import cache_manager
from utils.logger import log_manager


class DeviceRuntimeStatus(Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    COLLECTING = "collecting"
    PAUSED = "paused"
    ERROR = "error"
    DISABLED = "disabled"


class DeviceManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._runtime_status: Dict[str, DeviceRuntimeStatus] = {}
        self._last_comm_time: Dict[str, float] = {}
        self._comm_success_rate: Dict[str, float] = {}
        self._upload_success_rate: Dict[str, float] = {}
        self._alarm_checker = AlarmChecker()
        self._on_status_changed: Optional[Callable[[str, DeviceRuntimeStatus], None]] = None
        self._on_data_received: Optional[Callable[[CollectResult], None]] = None
        self._active = False

    def set_status_callback(self, callback: Callable[[str, DeviceRuntimeStatus], None]):
        self._on_status_changed = callback

    def set_data_callback(self, callback: Callable[[CollectResult], None]):
        self._on_data_received = callback

    def start_all(self):
        self._active = True
        for device_id in config_manager.devices:
            self._start_device(device_id)
        cache_manager.start_upload_worker()
        log_manager.info("设备管理", "所有设备已启动")

    def stop_all(self):
        self._active = False
        collector_manager.stop_all()
        cache_manager.stop_upload_worker()
        for device_id in config_manager.devices:
            mqtt_manager.disconnect_device(device_id)
        log_manager.info("设备管理", "所有设备已停止")

    def start_device(self, device_id: str) -> bool:
        device_config = config_manager.get_device(device_id)
        if not device_config or not device_config.enabled:
            self._set_runtime_status(device_id, DeviceRuntimeStatus.DISABLED)
            return False
        return self._start_device(device_id)

    def stop_device(self, device_id: str):
        collector_manager.stop_device(device_id)
        mqtt_manager.disconnect_device(device_id)
        self._set_runtime_status(device_id, DeviceRuntimeStatus.OFFLINE)
        log_manager.info(f"设备[{device_id}]", "设备已停止")

    def _start_device(self, device_id: str) -> bool:
        device_config = config_manager.get_device(device_id)
        if not device_config:
            return False
        if not device_config.enabled:
            self._set_runtime_status(device_id, DeviceRuntimeStatus.DISABLED)
            return False
        collector_manager.add_device(device_config)
        collector = collector_manager._collectors.get(device_id)
        if not collector:
            return False
        collector.set_data_callback(lambda result: self._on_collect_data(device_id, result))
        collector.set_batch_callback(lambda results: self._on_collect_batch(device_id, results))
        collector.set_status_callback(lambda status: self._on_collector_status(device_id, status))
        mqtt_conn = mqtt_manager.connect_device(device_id, device_config.mqtt)
        if not mqtt_conn:
            log_manager.warn(f"设备[{device_id}]", "MQTT连接失败，数据将缓存本地待补传")
        cache_manager.start_upload_worker()
        if not collector_manager.start_device(device_id):
            self._set_runtime_status(device_id, DeviceRuntimeStatus.ERROR)
            return False
        if device_config.backup_mqtt and device_config.backup_mqtt.host:
            mqtt_manager.set_backup(device_id, device_config.backup_mqtt)
        self._update_comm_stats(device_id, True)
        self._set_runtime_status(device_id, DeviceRuntimeStatus.COLLECTING)
        log_manager.info(f"设备[{device_id}]", "设备启动成功")
        return True

    def add_device(self, device_config: DeviceConfig) -> bool:
        if not config_manager.add_device(device_config):
            return False
        self._set_runtime_status(device_config.device_id, DeviceRuntimeStatus.OFFLINE)
        log_manager.info(f"设备[{device_config.device_id}]", "设备已添加")
        return True

    def remove_device(self, device_id: str) -> bool:
        self.stop_device(device_id)
        collector_manager.remove_device(device_id)
        mqtt_manager.remove_client(device_id)
        serial_manager.remove_client(device_id)
        ethernet_manager.remove_client(device_id)
        self._runtime_status.pop(device_id, None)
        if not config_manager.remove_device(device_id):
            return False
        log_manager.info(f"设备[{device_id}]", "设备已删除")
        return True

    def update_device(self, device_config: DeviceConfig) -> bool:
        was_running = self._runtime_status.get(device_config.device_id) == DeviceRuntimeStatus.COLLECTING
        self.stop_device(device_config.device_id)
        if not config_manager.update_device(device_config):
            return False
        if was_running:
            self.start_device(device_config.device_id)
        log_manager.info(f"设备[{device_config.device_id}]", "设备配置已更新")
        return True

    def get_device_status(self, device_id: str) -> dict:
        device_config = config_manager.get_device(device_id)
        runtime = self._runtime_status.get(device_id, DeviceRuntimeStatus.OFFLINE)
        collector_status = collector_manager.get_device_status(device_id)
        mqtt_state = mqtt_manager.get_device_state(device_id)
        return {
            'device_id': device_id,
            'name': device_config.name if device_config else "",
            'enabled': device_config.enabled if device_config else False,
            'runtime_status': runtime.value,
            'collector_status': collector_status.value,
            'mqtt_state': getattr(mqtt_state, 'value', mqtt_state or "disconnected"),
            'last_comm_time': self._last_comm_time.get(device_id, 0),
            'comm_success_rate': self._comm_success_rate.get(device_id, 0),
            'upload_success_rate': self._upload_success_rate.get(device_id, 0)
        }

    def get_all_device_status(self) -> List[dict]:
        return [self.get_device_status(did) for did in config_manager.devices.keys()]

    def get_device_latest_data(self, device_id: str) -> Dict[str, CollectResult]:
        return collector_manager.get_device_latest_values(device_id)

    def trigger_device_once(self, device_id: str) -> List[CollectResult]:
        collector = collector_manager._collectors.get(device_id)
        if collector:
            return collector.trigger_once()
        return []

    def force_upload_all_points(self, device_id: str) -> bool:
        device_config = config_manager.get_device(device_id)
        if not device_config:
            return False
        collector = collector_manager._collectors.get(device_id)
        latest = collector.latest_values if collector else {}
        transformer = DataTransformer(device_id, device_config.mqtt.topic_prefix)
        batch_data = []
        for point in device_config.collect.points:
            if not point.enabled:
                continue
            if point.name in latest:
                batch_data.append(transformer.transform_single(latest[point.name]))
            else:
                placeholder = CollectResult(
                    device_id=device_id,
                    point_name=point.name,
                    point_description=point.description,
                    value=None, raw_value=None,
                    unit=point.unit, timestamp=time.time(),
                    success=False, error_message="未采集"
                )
                batch_data.append(transformer.transform_single(placeholder))
        if not batch_data:
            return False
        topic = transformer.get_topic(data_type="telemetry")
        payload = json.dumps(batch_data, ensure_ascii=False)
        try:
            log_manager.info(f"设备[{device_id}]", f"全量上传: topic={topic}, 共{len(batch_data)}条")
            success = mqtt_manager.publish(device_id, topic, payload, device_config.mqtt.qos)
            if success:
                log_manager.info(f"设备[{device_id}]", "全量上传成功")
            else:
                log_manager.warn(f"设备[{device_id}]", "全量上传失败, 已缓存")
            return success
        except Exception as e:
            log_manager.error(f"设备[{device_id}]", f"全量上传异常: {e}")
            return False

    def get_alarms(self, limit: int = 100) -> List[dict]:
        return self._alarm_checker.get_recent_alarms(limit)

    def clear_alarms(self):
        self._alarm_checker.clear_history()

    def _on_collect_data(self, device_id: str, result: CollectResult):
        self._update_comm_stats(device_id, result.success)
        alarm = self._alarm_checker.check(result)
        if alarm:
            db.insert_alarm(
                device_id=result.device_id,
                point_name=result.point_name,
                value=result.value if result.value else 0,
                unit=result.unit,
                alarm_type=alarm['type'],
                threshold=alarm['threshold'] if alarm['threshold'] else 0,
                description=alarm['description'],
                timestamp=result.timestamp
            )
            log_manager.warn(f"设备[{device_id}]",
                             f"报警: {result.point_name}={result.value}{result.unit}")
        db.insert_data(
            device_id=result.device_id,
            point_name=result.point_name,
            value=result.value,
            unit=result.unit,
            timestamp=result.timestamp,
            success=result.success,
            is_alarm=result.is_alarm
        )
        if not config_manager.app_config.batch_publish:
            self._publish_single(device_id, result)
        if self._on_data_received:
            try:
                self._on_data_received(result)
            except Exception:
                pass

    def _publish_single(self, device_id: str, result: CollectResult):
        device_config = config_manager.get_device(device_id)
        if not device_config:
            return
        data_filter = DataFilter(device_config.data_filter)
        should_upload = data_filter.should_upload(result)
        if not should_upload:
            log_manager.info(f"设备[{device_id}]",
                             f"数据过滤未通过上传: {result.point_name}={result.value}, "
                             f"null_filter={data_filter.config.enable_null_filter}, "
                             f"threshold={data_filter.config.enable_threshold}, "
                             f"change_rate={data_filter.config.enable_change_rate}")
            return
        try:
            transformer = DataTransformer(device_id, device_config.mqtt.topic_prefix)
            json_data = transformer.transform_single(result)
            topic = transformer.get_topic(point_name=result.point_name)
            log_manager.info(f"设备[{device_id}]", f"准备发布: topic={topic}, value={result.value}")
            success = mqtt_manager.publish_json(device_id, topic, json_data, device_config.mqtt.qos)
            self._update_upload_stats(device_id, success)
            if not success:
                log_manager.warn(f"设备[{device_id}]", f"MQTT发布失败: topic={topic}, 已缓存")
        except Exception as e:
            log_manager.error(f"设备[{device_id}]", f"MQTT发布异常: {e}")
            self._update_upload_stats(device_id, False)
            cache_manager.cache_data(device_id, device_config.mqtt.topic_prefix,
                                     json.dumps({"device_id": result.device_id,
                                                 "point_name": result.point_name,
                                                 "value": str(result.value),
                                                 "unit": result.unit,
                                                 "timestamp": result.timestamp},
                                                ensure_ascii=False),
                                     device_config.mqtt.qos)

    def _on_collect_batch(self, device_id: str, results: List[CollectResult]):
        device_config = config_manager.get_device(device_id)
        if not device_config:
            return
        if not config_manager.app_config.batch_publish:
            return
        filtered = []
        data_filter = DataFilter(device_config.data_filter)
        for r in results:
            if data_filter.should_upload(r):
                filtered.append(r)
            else:
                log_manager.info(f"设备[{device_id}]",
                                 f"数据过滤未通过上传: {r.point_name}={r.value}, "
                                 f"null_filter={data_filter.config.enable_null_filter}, "
                                 f"threshold={data_filter.config.enable_threshold}, "
                                 f"change_rate={data_filter.config.enable_change_rate}")
        if not filtered:
            return
        transformer = DataTransformer(device_id, device_config.mqtt.topic_prefix)
        batch_data = [transformer.transform_single(r) for r in filtered]
        topic = transformer.get_topic(data_type="telemetry")
        payload = json.dumps(batch_data, ensure_ascii=False)
        try:
            log_manager.info(f"设备[{device_id}]", f"批量发布: topic={topic}, 共{len(batch_data)}条")
            success = mqtt_manager.publish(device_id, topic, payload, device_config.mqtt.qos)
            for _ in filtered:
                self._update_upload_stats(device_id, success)
            if not success:
                log_manager.warn(f"设备[{device_id}]", f"批量MQTT发布失败, 已缓存")
        except Exception as e:
            log_manager.error(f"设备[{device_id}]", f"批量MQTT发布异常: {e}")
            for _ in filtered:
                self._update_upload_stats(device_id, False)

    def _on_collector_status(self, device_id: str, status: DeviceStatus):
        if status == DeviceStatus.ERROR:
            self._set_runtime_status(device_id, DeviceRuntimeStatus.ERROR)
        elif status == DeviceStatus.STOPPED:
            self._set_runtime_status(device_id, DeviceRuntimeStatus.OFFLINE)

    def _set_runtime_status(self, device_id: str, status: DeviceRuntimeStatus):
        if self._runtime_status.get(device_id) != status:
            self._runtime_status[device_id] = status
            if self._on_status_changed:
                try:
                    self._on_status_changed(device_id, status)
                except Exception:
                    pass

    def _update_comm_stats(self, device_id: str, success: bool):
        self._last_comm_time[device_id] = time.time()
        old_rate = self._comm_success_rate.get(device_id, 100.0)
        if success:
            self._comm_success_rate[device_id] = old_rate * 0.9 + 10.0
        else:
            self._comm_success_rate[device_id] = old_rate * 0.9
        self._comm_success_rate[device_id] = min(100.0, max(0.0, self._comm_success_rate[device_id]))

    def _update_upload_stats(self, device_id: str, success: bool):
        old_rate = self._upload_success_rate.get(device_id, 100.0)
        if success:
            self._upload_success_rate[device_id] = old_rate * 0.9 + 10.0
        else:
            self._upload_success_rate[device_id] = old_rate * 0.9
        self._upload_success_rate[device_id] = min(100.0, max(0.0, self._upload_success_rate[device_id]))


device_manager = DeviceManager()