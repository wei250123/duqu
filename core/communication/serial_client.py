import time
import threading
from typing import Optional, Callable, List
from enum import Enum

import serial
import serial.tools.list_ports

from config.config_manager import SerialConfig
from utils.logger import log_manager


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class SerialClient:
    PARITY_MAP = {
        'N': serial.PARITY_NONE,
        'E': serial.PARITY_EVEN,
        'O': serial.PARITY_ODD,
        'M': serial.PARITY_MARK,
        'S': serial.PARITY_SPACE
    }
    FLOW_MAP = {
        'none': False,
        'hardware': True,
        'software': False
    }

    def __init__(self, config: SerialConfig, device_id: str = ""):
        self._config = config
        self._device_id = device_id
        self._serial: Optional[serial.Serial] = None
        self._state = ConnectionState.DISCONNECTED
        self._running = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_attempts = 0
        self._rx_buffer = bytearray()
        self._on_data_received: Optional[Callable[[bytes], None]] = None
        self._on_state_changed: Optional[Callable[[ConnectionState], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._data_mode = "hex"
        self._rx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._tx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._send_recv_lock = threading.Lock()

    def set_data_callback(self, callback: Callable[[bytes], None]):
        self._on_data_received = callback

    def set_state_callback(self, callback: Callable[[ConnectionState], None]):
        self._on_state_changed = callback

    def set_error_callback(self, callback: Callable[[str], None]):
        self._on_error = callback

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._serial is not None and self._serial.is_open

    @property
    def config(self) -> SerialConfig:
        return self._config

    @config.setter
    def config(self, value: SerialConfig):
        self._config = value

    @property
    def rx_stats(self) -> dict:
        return dict(self._rx_stats)

    @property
    def tx_stats(self) -> dict:
        return dict(self._tx_stats)

    def reset_stats(self):
        self._rx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._tx_stats = {"bytes": 0, "packets": 0, "errors": 0}

    @staticmethod
    def scan_ports() -> List[dict]:
        ports = []
        for port_info in serial.tools.list_ports.comports():
            ports.append({
                'device': port_info.device,
                'name': port_info.name,
                'description': port_info.description,
                'hwid': port_info.hwid,
                'vid': port_info.vid,
                'pid': port_info.pid,
                'manufacturer': port_info.manufacturer,
                'product': port_info.product,
                'serial_number': port_info.serial_number
            })
        return ports

    def connect(self) -> bool:
        if self._state == ConnectionState.CONNECTED:
            return True
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._serial = serial.Serial()
            self._serial.port = self._config.port
            self._serial.baudrate = self._config.baudrate
            self._serial.bytesize = self._config.bytesize
            self._serial.parity = self.PARITY_MAP.get(self._config.parity, serial.PARITY_NONE)
            self._serial.stopbits = self._config.stopbits
            self._serial.timeout = self._config.timeout
            if self._config.flow_control == 'hardware':
                self._serial.rtscts = True
            elif self._config.flow_control == 'software':
                self._serial.xonxoff = True
            self._serial.open()
            self._running = True
            self._reconnect_attempts = 0
            self._set_state(ConnectionState.CONNECTED)
            log_manager.info(f"串口[{self._device_id}]", f"已连接到 {self._config.port}, 波特率:{self._config.baudrate}")
            return True
        except Exception as e:
            self._set_state(ConnectionState.ERROR)
            log_manager.error(f"串口[{self._device_id}]", f"连接失败: {e}")
            if self._config.auto_reconnect:
                self._start_reconnect()
            return False

    def disconnect(self):
        self._running = False
        self._reconnect_attempts = 0
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self._set_state(ConnectionState.DISCONNECTED)
        log_manager.info(f"串口[{self._device_id}]", "已断开连接")

    def send(self, data: bytes) -> bool:
        if not self.is_connected:
            log_manager.warn(f"串口[{self._device_id}]", "发送失败: 未连接")
            return False
        try:
            self._serial.write(data)
            self._serial.flush()
            self._tx_stats["bytes"] += len(data)
            self._tx_stats["packets"] += 1
            return True
        except Exception as e:
            self._tx_stats["errors"] += 1
            log_manager.error(f"串口[{self._device_id}]", f"发送失败: {e}")
            return False

    def send_hex(self, hex_str: str) -> bool:
        from utils.helpers import hex_to_bytes
        try:
            data = hex_to_bytes(hex_str)
            return self.send(data)
        except Exception as e:
            log_manager.error(f"串口[{self._device_id}]", f"HEX发送失败: {e}")
            return False

    def send_ascii(self, text: str) -> bool:
        try:
            data = text.encode('ascii')
            return self.send(data)
        except Exception as e:
            log_manager.error(f"串口[{self._device_id}]", f"ASCII发送失败: {e}")
            return False

    def read(self, timeout: Optional[float] = None) -> Optional[bytes]:
        if not self.is_connected:
            return None
        old_timeout = self._serial.timeout
        if timeout is not None:
            self._serial.timeout = timeout
        try:
            if self._serial.in_waiting:
                data = self._serial.read(self._serial.in_waiting)
                self._rx_stats["bytes"] += len(data)
                self._rx_stats["packets"] += 1
                return data
            return None
        except Exception as e:
            self._rx_stats["errors"] += 1
            log_manager.error(f"串口[{self._device_id}]", f"读取失败: {e}")
            return None
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout

    def read_bytes(self, count: int, timeout: Optional[float] = None) -> bytes:
        if not self.is_connected:
            return b''
        old_timeout = self._serial.timeout
        if timeout is not None:
            self._serial.timeout = timeout
        try:
            data = self._serial.read(count)
            self._rx_stats["bytes"] += len(data)
            self._rx_stats["packets"] += 1
            return data
        except Exception as e:
            self._rx_stats["errors"] += 1
            return b''
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout

    def read_until(self, expected: bytes, timeout: Optional[float] = None) -> bytes:
        if not self.is_connected:
            return b''
        old_timeout = self._serial.timeout
        if timeout is not None:
            self._serial.timeout = timeout
        try:
            data = self._serial.read_until(expected)
            self._rx_stats["bytes"] += len(data)
            self._rx_stats["packets"] += 1
            return data
        except Exception as e:
            self._rx_stats["errors"] += 1
            return b''
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout

    def send_and_receive_for_protocol(self, command: bytes, timeout: float = 1.0) -> Optional[bytes]:
        if not self.is_connected:
            return None
        with self._send_recv_lock:
            try:
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                self.send(command)
            except Exception:
                return None
            return self.read_until(b'', timeout=timeout)

    def get_in_waiting(self) -> int:
        if self.is_connected:
            return self._serial.in_waiting
        return 0

    def _set_state(self, state: ConnectionState):
        if self._state != state:
            self._state = state
            if self._on_state_changed:
                try:
                    self._on_state_changed(state)
                except Exception:
                    pass

    def _start_reconnect(self):
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True,
                                                  name=f"SerialReconnect-{self._device_id}")
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        while self._running is False and self._config.auto_reconnect:
            if self._config.reconnect_max_times > 0 and self._reconnect_attempts >= self._config.reconnect_max_times:
                log_manager.warn(f"串口[{self._device_id}]", f"已达最大重连次数({self._config.reconnect_max_times})，停止重连")
                self._set_state(ConnectionState.ERROR)
                return
            self._set_state(ConnectionState.RECONNECTING)
            self._reconnect_attempts += 1
            log_manager.info(f"串口[{self._device_id}]",
                             f"第{self._reconnect_attempts}次尝试重连...")
            if self.connect():
                return
            time.sleep(self._config.reconnect_interval)


class SerialManager:
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
        self._clients: dict[str, SerialClient] = {}
        self._port_to_client: dict[str, SerialClient] = {}
        self._port_refs: dict[str, set] = {}
        self._hotplug_thread: Optional[threading.Thread] = None
        self._hotplug_running = False
        self._known_ports: set = set()

    def _make_key(self, config: SerialConfig) -> str:
        return f"{config.port}:{config.baudrate}:{config.bytesize}:{config.parity}:{config.stopbits}"

    def get_client(self, device_id: str, config: SerialConfig) -> SerialClient:
        port_key = self._make_key(config)
        if port_key in self._port_to_client:
            client = self._port_to_client[port_key]
            client.config = config
            self._port_refs.setdefault(port_key, set()).add(device_id)
            self._clients[device_id] = client
            return client
        client = SerialClient(config, device_id)
        self._clients[device_id] = client
        self._port_to_client[port_key] = client
        self._port_refs.setdefault(port_key, set()).add(device_id)
        return client

    def remove_client(self, device_id: str):
        if device_id not in self._clients:
            return
        client = self._clients.pop(device_id)
        for port_key, port_refs in list(self._port_refs.items()):
            if device_id in port_refs:
                port_refs.discard(device_id)
                if not port_refs:
                    client.disconnect()
                    del self._port_refs[port_key]
                    if self._port_to_client.get(port_key) is client:
                        del self._port_to_client[port_key]
                break

    def connect_device(self, device_id: str, config: SerialConfig) -> bool:
        client = self.get_client(device_id, config)
        return client.connect()

    def disconnect_device(self, device_id: str):
        self.remove_client(device_id)

    def get_device_state(self, device_id: str) -> ConnectionState:
        if device_id in self._clients:
            return self._clients[device_id].state
        return ConnectionState.DISCONNECTED

    def start_hotplug_detection(self, check_interval: float = 2.0):
        if self._hotplug_running:
            return
        self._hotplug_running = True
        self._known_ports = {p['device'] for p in SerialClient.scan_ports()}
        self._hotplug_thread = threading.Thread(target=self._hotplug_loop, daemon=True,
                                                args=(check_interval,), name="HotplugDetector")
        self._hotplug_thread.start()
        log_manager.info("串口管理", "热插拔检测已启动")

    def stop_hotplug_detection(self):
        self._hotplug_running = False

    def _hotplug_loop(self, check_interval: float):
        while self._hotplug_running:
            try:
                current_ports = {p['device'] for p in SerialClient.scan_ports()}
                removed = self._known_ports - current_ports
                added = current_ports - self._known_ports
                if removed:
                    log_manager.info("串口管理", f"检测到串口移除: {removed}")
                    for port in removed:
                        for device_id, client in self._clients.items():
                            if client.config.port == port and client.is_connected:
                                log_manager.warn("串口管理", f"设备[{device_id}]串口{port}已断开")
                                client._set_state(ConnectionState.DISCONNECTED)
                if added:
                    log_manager.info("串口管理", f"检测到串口插入: {added}")
                self._known_ports = current_ports
            except Exception as e:
                log_manager.error("串口管理", f"热插拔检测异常: {e}")
            time.sleep(check_interval)


serial_manager = SerialManager()