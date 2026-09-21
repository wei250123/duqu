import time
import threading
from typing import Optional, Callable, Dict, List, Any

from config.config_manager import DeviceConfig, CollectPoint
from core.data_types import CollectResult, CollectMode, DeviceStatus
from core.communication.serial_client import SerialClient, serial_manager
from core.communication.ethernet_client import EthernetClient, ethernet_manager
from core.communication.protocol_base import ProtocolResponse
from core.protocols.protocol_factory import protocol_factory
from core.processor.pipeline import Pipeline
from core.processor.json_formatter import json_formatter
from utils.logger import log_manager


class DeviceCollector:
    def __init__(self, device_config: DeviceConfig):
        self._config = device_config
        self._status = DeviceStatus.STOPPED
        self._mode = CollectMode.TIMER
        self._running_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._protocol = None
        self._serial_client: Optional[SerialClient] = None
        self._ethernet_client: Optional[EthernetClient] = None
        self._on_data: Optional[Callable[[CollectResult], None]] = None
        self._on_status_changed: Optional[Callable[[DeviceStatus], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_json_output: Optional[Callable[[str], None]] = None
        self._on_batch: Optional[Callable[[List[CollectResult]], None]] = None
        self._latest_values: Dict[str, CollectResult] = {}
        self._collect_stats = {"success": 0, "fail": 0, "total": 0, "last_time": 0.0}
        self._pipeline = Pipeline(device_config)
        self._init_protocol()

    def _init_protocol(self):
        self._protocol = protocol_factory.create_protocol(self._config)

    def set_data_callback(self, callback: Callable[[CollectResult], None]):
        self._on_data = callback

    def set_status_callback(self, callback: Callable[[DeviceStatus], None]):
        self._on_status_changed = callback

    def set_error_callback(self, callback: Callable[[str], None]):
        self._on_error = callback

    def set_batch_callback(self, callback: Callable[[List[CollectResult]], None]):
        self._on_batch = callback

    def set_json_output_callback(self, callback: Callable[[str], None]):
        self._on_json_output = callback

    @property
    def status(self) -> DeviceStatus:
        return self._status

    @property
    def config(self) -> DeviceConfig:
        return self._config

    @config.setter
    def config(self, value: DeviceConfig):
        self._config = value
        self._pipeline.pipeline_config = value.pipeline
        self._init_protocol()

    @property
    def latest_values(self) -> Dict[str, CollectResult]:
        return dict(self._latest_values)

    @property
    def stats(self) -> dict:
        return dict(self._collect_stats)

    def start(self) -> bool:
        if self._status == DeviceStatus.RUNNING:
            return True
        try:
            if not self._connect():
                log_manager.error(f"采集器[{self._config.device_id}]", "无法连接设备")
                return False
        except Exception as e:
            log_manager.error(f"采集器[{self._config.device_id}]", f"连接异常: {e}")
            return False
        self._running_event.set()
        self._set_status(DeviceStatus.RUNNING)
        self._mode = self._resolve_mode()
        self._thread = threading.Thread(target=self._collect_loop, daemon=True,
                                        name=f"Collector-{self._config.device_id}")
        self._thread.start()
        log_manager.info(f"采集器[{self._config.device_id}]", f"已启动, 模式:{self._mode.value}")
        return True

    def _resolve_mode(self) -> CollectMode:
        mode_str = self._config.collect.mode
        try:
            return CollectMode(mode_str)
        except ValueError:
            log_manager.warn(f"采集器[{self._config.device_id}]", f"未知采集模式: {mode_str}, 使用默认timer模式")
            return CollectMode.TIMER

    def switch_mode(self, mode: str) -> bool:
        """运行时切换采集模式"""
        try:
            new_mode = CollectMode(mode)
        except ValueError:
            log_manager.warn(f"采集器[{self._config.device_id}]", f"无效的采集模式: {mode}")
            return False
        if self._mode == new_mode:
            return True
        self._mode = new_mode
        self._config.collect.mode = mode
        log_manager.info(f"采集器[{self._config.device_id}]", f"采集模式切换为: {new_mode.value}")
        return True

    @property
    def mode(self) -> CollectMode:
        return self._mode

    def stop(self):
        self._running_event.clear()
        self._set_status(DeviceStatus.STOPPED)
        self._disconnect()
        log_manager.info(f"采集器[{self._config.device_id}]", "已停止")

    def pause(self):
        if self._status == DeviceStatus.RUNNING:
            self._running_event.clear()
            self._set_status(DeviceStatus.PAUSED)
            log_manager.info(f"采集器[{self._config.device_id}]", "已暂停")

    def resume(self):
        if self._status == DeviceStatus.PAUSED:
            self._running_event.set()
            self._set_status(DeviceStatus.RUNNING)
            log_manager.info(f"采集器[{self._config.device_id}]", "已恢复")

    def trigger_once(self) -> List[CollectResult]:
        results = self._collect_all_points()
        batch_results = []
        for result in results:
            processed = self._pipeline.process(result)
            if processed:
                self._latest_values[processed.point_name] = processed
                batch_results.append(processed)
                if self._on_data:
                    try:
                        self._on_data(processed)
                    except Exception:
                        pass
        if batch_results and self._on_batch:
            try:
                self._on_batch(batch_results)
            except Exception:
                pass
        return results

    def trigger_point(self, point_name: str) -> Optional[CollectResult]:
        for point in self._config.collect.points:
            if point.name == point_name and point.enabled:
                return self._collect_point(point)
        return None

    def reset_stats(self):
        self._collect_stats = {"success": 0, "fail": 0, "total": 0, "last_time": 0.0}

    def _connect(self) -> bool:
        proto_type = self._config.protocol.protocol_type
        if proto_type in ('modbus_rtu', 'custom'):
            if not self._config.serial.port:
                log_manager.error(f"采集器[{self._config.device_id}]", "串口未配置")
                return False
            self._serial_client = serial_manager.get_client(self._config.device_id, self._config.serial)
            if not self._serial_client.connect():
                return False
            self._serial_client.set_data_callback(self._on_serial_data)
        elif proto_type in ('modbus_tcp', 'modbus_rtu_over_tcp'):
            self._ethernet_client = ethernet_manager.get_client(self._config.device_id, self._config.ethernet)
            if not self._ethernet_client.connect():
                return False
            self._ethernet_client.set_data_callback(self._on_ethernet_data)
        else:
            log_manager.warning(f"采集器[{self._config.device_id}]", f"未知协议类型: {proto_type}")
        return True

    def _disconnect(self):
        self._serial_client = None
        self._ethernet_client = None

    def _set_status(self, status: DeviceStatus):
        if self._status != status:
            self._status = status
            if self._on_status_changed:
                try:
                    self._on_status_changed(status)
                except Exception:
                    pass

    def _on_serial_data(self, data: bytes):
        pass
    
    def _on_ethernet_data(self, data: bytes, client_addr: Optional[str] = None):
        pass

    def _collect_loop(self):
        while True:
            self._running_event.wait()
            try:
                start_time = time.time()
                results = self._collect_all_points()
                batch_results = []
                for result in results:
                    processed = self._pipeline.process(result)
                    if processed:
                        self._latest_values[processed.point_name] = processed
                        batch_results.append(processed)
                        if self._on_data:
                            try:
                                self._on_data(processed)
                            except Exception:
                                pass
                if batch_results and self._on_batch:
                    try:
                        self._on_batch(batch_results)
                    except Exception:
                        pass
                if batch_results and self._pipeline.pipeline_config.enabled:
                    json_output = self._pipeline.output_json_batch(batch_results)
                    if json_output and self._on_json_output:
                        try:
                            self._on_json_output(json_output)
                        except Exception:
                            pass
                elapsed = time.time() - start_time
                if self._mode == CollectMode.CONTINUOUS:
                    # 及采及入：立即进入下一轮采集，不留间隔
                    pass
                else:
                    interval = max(0, (self._config.collect.interval_ms / 1000.0) - elapsed)
                    if interval > 0:
                        self._running_event.wait(interval)
            except Exception as e:
                log_manager.error(f"采集器[{self._config.device_id}]", f"采集循环异常: {e}")
                self._collect_stats["fail"] += 1
                time.sleep(1)

    def _collect_all_points(self) -> List[CollectResult]:
        results = []
        points = sorted(
            [p for p in self._config.collect.points if p.enabled],
            key=lambda x: -x.priority
        )
        for point in points:
            retries = max(1, self._config.collect.retry_times)
            result = CollectResult(
                device_id=self._config.device_id, point_name=point.name,
                point_description=point.description, value=None, raw_value=None,
                unit=point.unit, timestamp=time.time(), success=False,
                error_message="未采集"
            )
            for attempt in range(retries):
                result = self._collect_point(point)
                if result.success:
                    break
                time.sleep(self._config.collect.retry_interval_ms / 1000.0)
            results.append(result)
            self._collect_stats["total"] += 1
            if result.success:
                self._collect_stats["success"] += 1
            else:
                self._collect_stats["fail"] += 1
        self._collect_stats["last_time"] = time.time()
        return results

    def _collect_point(self, point: CollectPoint) -> CollectResult:
        command = self._protocol.build_read_command(point)
        if not command:
            return CollectResult(
                device_id=self._config.device_id,
                point_name=point.name,
                point_description=point.description,
                value=None, raw_value=None, unit=point.unit,
                timestamp=time.time(), success=False,
                error_message="指令构建失败"
            )
        raw_response = None
        response = None
        proto_type = self._config.protocol.protocol_type
        try:
            if proto_type == 'modbus_rtu' or proto_type == 'custom':
                raw_response = self._serial_client.send_and_receive_for_protocol(
                    command, timeout=self._config.collect.timeout_ms / 1000.0
                )
            elif proto_type in ('modbus_tcp', 'modbus_rtu_over_tcp'):
                raw_response = self._collect_tcp_point(command)
            else:
                return CollectResult(
                    device_id=self._config.device_id,
                    point_name=point.name,
                    point_description=point.description,
                    value=None, raw_value=None, unit=point.unit,
                    timestamp=time.time(), success=False,
                    error_message=f"不支持的协议类型: {proto_type}"
                )
            if raw_response is None:
                return CollectResult(
                    device_id=self._config.device_id,
                    point_name=point.name, point_description=point.description,
                    value=None, raw_value=None, unit=point.unit,
                    timestamp=time.time(), success=False,
                    error_message="无响应数据"
                )
            response = self._protocol.parse_response(raw_response, point)
        except Exception as e:
            return CollectResult(
                device_id=self._config.device_id,
                point_name=point.name, point_description=point.description,
                value=None, raw_value=None, unit=point.unit,
                timestamp=time.time(), success=False,
                error_message=str(e)
            )
        result = CollectResult(
            device_id=self._config.device_id,
            point_name=point.name,
            point_description=point.description,
            value=response.data if response.success else None,
            raw_value=response.data,
            unit=point.unit,
            timestamp=response.timestamp if response.timestamp else time.time(),
            success=response.success,
            error_message=response.error_message,
            alarm_high=point.alarm_high,
            alarm_low=point.alarm_low
        )
        if result.success and result.value is not None:
            if point.alarm_high is not None and result.value > point.alarm_high:
                result.is_alarm = True
            if point.alarm_low is not None and result.value < point.alarm_low:
                result.is_alarm = True
        return result

    def _collect_tcp_point(self, command: bytes) -> Optional[bytes]:
        if not self._ethernet_client:
            return None
        try:
            if self._config.protocol.protocol_type == 'modbus_rtu_over_tcp':
                from utils.helpers import bytes_to_hex
                log_manager.debug(f"采集器[{self._config.device_id}]",
                                  f"RTU-over-TCP TX({len(command)}B): {bytes_to_hex(command)}")
                result = self._ethernet_client.send_and_receive_raw(
                    command, timeout=self._config.collect.timeout_ms / 1000.0
                )
                if result:
                    log_manager.debug(f"采集器[{self._config.device_id}]",
                                      f"RTU-over-TCP RX({len(result)}B): {bytes_to_hex(result)}")
                return result
            return self._ethernet_client.send_and_receive(
                command, timeout=self._config.collect.timeout_ms / 1000.0
            )
        except Exception:
            return None


class CollectorManager:
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
        self._collectors: Dict[str, DeviceCollector] = {}

    def add_device(self, device_config: DeviceConfig):
        collector = DeviceCollector(device_config)
        self._collectors[device_config.device_id] = collector

    def remove_device(self, device_id: str):
        if device_id in self._collectors:
            self._collectors[device_id].stop()
            del self._collectors[device_id]

    def start_device(self, device_id: str) -> bool:
        collector = self._collectors.get(device_id)
        if not collector:
            return False
        return collector.start()

    def stop_device(self, device_id: str):
        collector = self._collectors.get(device_id)
        if collector:
            collector.stop()

    def pause_device(self, device_id: str):
        collector = self._collectors.get(device_id)
        if collector:
            collector.pause()

    def resume_device(self, device_id: str):
        collector = self._collectors.get(device_id)
        if collector:
            collector.resume()

    def get_device_status(self, device_id: str) -> DeviceStatus:
        collector = self._collectors.get(device_id)
        return collector.status if collector else DeviceStatus.STOPPED

    def get_device_latest_values(self, device_id: str) -> Dict[str, CollectResult]:
        collector = self._collectors.get(device_id)
        return collector.latest_values if collector else {}

    def get_device_stats(self, device_id: str) -> dict:
        collector = self._collectors.get(device_id)
        return collector.stats if collector else {}

    def switch_device_mode(self, device_id: str, mode: str) -> bool:
        collector = self._collectors.get(device_id)
        if not collector:
            return False
        return collector.switch_mode(mode)

    def get_device_mode(self, device_id: str) -> str:
        collector = self._collectors.get(device_id)
        return collector.mode.value if collector else CollectMode.TIMER.value

    def start_all(self):
        for collector in self._collectors.values():
            if collector.config.enabled:
                collector.start()

    def stop_all(self):
        for collector in self._collectors.values():
            collector.stop()

    def trigger_all_once(self) -> Dict[str, List[CollectResult]]:
        results = {}
        for device_id, collector in self._collectors.items():
            results[device_id] = collector.trigger_once()
        return results

    def get_all_status(self) -> Dict[str, dict]:
        status = {}
        for device_id, collector in self._collectors.items():
            status[device_id] = {
                'status': collector.status.value,
                'stats': collector.stats,
                'points_count': len(collector.latest_values)
            }
        return status


collector_manager = CollectorManager()