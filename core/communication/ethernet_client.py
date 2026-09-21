import os
import sys
import time
import socket
import select
import struct
import threading
import subprocess
from typing import Optional, Callable, List, Dict, Tuple
from enum import Enum
from dataclasses import dataclass

from config.config_manager import EthernetConfig
from utils.logger import log_manager
from utils.helpers import is_valid_ip, is_valid_port, exponential_backoff


class EthernetMode(Enum):
    TCP_CLIENT = "tcp_client"
    TCP_SERVER = "tcp_server"
    UDP = "udp"


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    LISTENING = "listening"
    ERROR = "error"


@dataclass
class TcpConnection:
    sock: socket.socket
    addr: Tuple[str, int]
    connected_at: float
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0


class EthernetClient:
    def __init__(self, config: EthernetConfig, device_id: str = ""):
        self._config = config
        self._device_id = device_id
        self._sock: Optional[socket.socket] = None
        self._state = ConnectionState.DISCONNECTED
        self._mode = EthernetMode.TCP_CLIENT
        self._running = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_attempts = 0
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: Dict[str, TcpConnection] = {}
        self._on_data_received: Optional[Callable[[bytes, Optional[str]], None]] = None
        self._on_state_changed: Optional[Callable[[ConnectionState], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_client_connected: Optional[Callable[[str], None]] = None
        self._on_client_disconnected: Optional[Callable[[str], None]] = None
        self._rx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._tx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._io_lock = threading.Lock()
        self._parse_mode()

    def _parse_mode(self):
        mode_str = self._config.mode.lower()
        if 'udp' in mode_str:
            self._mode = EthernetMode.UDP
        elif 'server' in mode_str:
            self._mode = EthernetMode.TCP_SERVER
        else:
            self._mode = EthernetMode.TCP_CLIENT

    def set_data_callback(self, callback: Callable[[bytes, Optional[str]], None]):
        self._on_data_received = callback

    def set_state_callback(self, callback: Callable[[ConnectionState], None]):
        self._on_state_changed = callback

    def set_error_callback(self, callback: Callable[[str], None]):
        self._on_error = callback

    def set_client_connect_callback(self, callback: Callable[[str], None]):
        self._on_client_connected = callback

    def set_client_disconnect_callback(self, callback: Callable[[str], None]):
        self._on_client_disconnected = callback

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        if self._mode == EthernetMode.TCP_SERVER:
            return self._state == ConnectionState.LISTENING
        return self._state == ConnectionState.CONNECTED and self._sock is not None

    @property
    def config(self) -> EthernetConfig:
        return self._config

    @config.setter
    def config(self, value: EthernetConfig):
        self._config = value
        self._parse_mode()

    @property
    def rx_stats(self) -> dict:
        return dict(self._rx_stats)

    @property
    def tx_stats(self) -> dict:
        return dict(self._tx_stats)

    @property
    def connected_clients(self) -> List[dict]:
        return [
            {
                'addr': f"{conn.addr[0]}:{conn.addr[1]}",
                'connected_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(conn.connected_at)),
                'rx_bytes': conn.rx_bytes,
                'tx_bytes': conn.tx_bytes
            }
            for conn in self._clients.values()
        ]

    def reset_stats(self):
        self._rx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        self._tx_stats = {"bytes": 0, "packets": 0, "errors": 0}
        for conn in self._clients.values():
            conn.rx_bytes = 0
            conn.tx_bytes = 0

    def connect(self) -> bool:
        if self._mode == EthernetMode.TCP_SERVER:
            return self._start_server()
        elif self._mode == EthernetMode.UDP:
            return self._connect_udp()
        else:
            return self._connect_tcp()

    def _connect_tcp(self) -> bool:
        if self._state == ConnectionState.CONNECTED:
            return True
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self._config.timeout)
            if self._config.local_port > 0:
                self._sock.bind(('', self._config.local_port))
            self._sock.connect((self._config.host, self._config.port))
            self._sock.settimeout(None)
            self._sock.setblocking(False)
            self._running = True
            self._reconnect_attempts = 0
            self._set_state(ConnectionState.CONNECTED)
            log_manager.info(f"以太网[{self._device_id}]", f"TCP已连接到 {self._config.host}:{self._config.port}")
            threading.Thread(target=self._receive_loop, daemon=True,
                             name=f"EthRx-{self._device_id}").start()
            return True
        except Exception as e:
            self._set_state(ConnectionState.ERROR)
            log_manager.error(f"以太网[{self._device_id}]", f"TCP连接失败: {e}")
            if self._config.auto_reconnect:
                self._start_reconnect()
            return False

    def _start_server(self) -> bool:
        if self._state == ConnectionState.LISTENING:
            return True
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._config.host or '0.0.0.0', self._config.port))
            self._sock.listen(self._config.max_connections)
            self._sock.setblocking(False)
            self._running = True
            self._set_state(ConnectionState.LISTENING)
            log_manager.info(f"以太网[{self._device_id}]", f"TCP服务器已启动，监听端口 {self._config.port}")
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True,
                                                   name=f"EthAccept-{self._device_id}")
            self._accept_thread.start()
            return True
        except Exception as e:
            self._set_state(ConnectionState.ERROR)
            log_manager.error(f"以太网[{self._device_id}]", f"TCP服务器启动失败: {e}")
            return False

    def _connect_udp(self) -> bool:
        if self._state == ConnectionState.CONNECTED:
            return True
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self._config.timeout)
            if self._config.local_port > 0:
                self._sock.bind(('', self._config.local_port))
            self._sock.connect((self._config.host, self._config.port))
            self._sock.settimeout(None)
            self._sock.setblocking(False)
            self._running = True
            self._reconnect_attempts = 0
            self._set_state(ConnectionState.CONNECTED)
            log_manager.info(f"以太网[{self._device_id}]", f"UDP已绑定到 {self._config.host}:{self._config.port}")
            threading.Thread(target=self._receive_loop, daemon=True,
                             name=f"EthRx-{self._device_id}").start()
            return True
        except Exception as e:
            self._set_state(ConnectionState.ERROR)
            log_manager.error(f"以太网[{self._device_id}]", f"UDP连接失败: {e}")
            return False

    def disconnect(self):
        self._running = False
        self._reconnect_attempts = 0
        for client_id in list(self._clients.keys()):
            try:
                self._clients[client_id].sock.close()
            except Exception:
                pass
        self._clients.clear()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._set_state(ConnectionState.DISCONNECTED)
        log_manager.info(f"以太网[{self._device_id}]", "已断开连接")

    def send(self, data: bytes, client_addr: Optional[str] = None) -> bool:
        if self._mode == EthernetMode.TCP_SERVER:
            if client_addr and client_addr in self._clients:
                try:
                    conn = self._clients[client_addr]
                    conn.sock.sendall(data)
                    conn.tx_bytes += len(data)
                    conn.tx_packets += 1
                    self._tx_stats["bytes"] += len(data)
                    self._tx_stats["packets"] += 1
                    return True
                except Exception as e:
                    self._tx_stats["errors"] += 1
                    log_manager.error(f"以太网[{self._device_id}]", f"发送到{client_addr}失败: {e}")
                    return False
            elif self._clients:
                success = True
                for addr, conn in self._clients.items():
                    try:
                        conn.sock.sendall(data)
                        conn.tx_bytes += len(data)
                        conn.tx_packets += 1
                    except Exception:
                        success = False
                return success
            return False
        if not self.is_connected:
            return False
        try:
            self._sock.sendall(data)
            self._tx_stats["bytes"] += len(data)
            self._tx_stats["packets"] += 1
            return True
        except Exception as e:
            self._tx_stats["errors"] += 1
            self._set_state(ConnectionState.DISCONNECTED)
            self._running = False
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            self._start_reconnect()
            log_manager.error(f"以太网[{self._device_id}]", f"发送失败: {e}")
            return False

    def send_and_receive(self, data: bytes, timeout: float = 3.0) -> Optional[bytes]:
        if not self.is_connected or self._mode != EthernetMode.TCP_CLIENT:
            return None
        with self._io_lock:
            if not self.send(data):
                return None
            try:
                self._sock.settimeout(timeout)
                response = b''
                while True:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if len(response) >= 8:
                        try:
                            remaining = 6 + struct.unpack('>H', response[4:6])[0]
                            if len(response) >= remaining:
                                break
                        except Exception:
                            break
                return response if response else None
            except socket.timeout:
                return None
            except Exception:
                return None

            
    def send_and_receive_raw(self, data: bytes, timeout: float = 3.0,
                             expect_min_bytes: int = 0) -> Optional[bytes]:
        if not self.is_connected or self._mode != EthernetMode.TCP_CLIENT:
            return None
        with self._io_lock:
            if not self.send(data):
                return None
            try:
                self._sock.settimeout(timeout)
                response = b''
                while True:
                    try:
                        chunk = self._sock.recv(4096)
                    except socket.timeout:
                        break
                    except Exception:
                        break
                    if not chunk:
                        break
                    response += chunk
                    if expect_min_bytes > 0 and len(response) >= expect_min_bytes:
                        break
            except Exception:
                pass
            try:
                self._sock.settimeout(None)
                self._sock.setblocking(False)
            except Exception:
                pass
            return response if response else None

    def send_hex(self, hex_str: str, client_addr: Optional[str] = None) -> bool:
        from utils.helpers import hex_to_bytes
        try:
            return self.send(hex_to_bytes(hex_str), client_addr)
        except Exception as e:
            log_manager.error(f"以太网[{self._device_id}]", f"HEX发送失败: {e}")
            return False

    def send_ascii(self, text: str, client_addr: Optional[str] = None) -> bool:
        try:
            return self.send(text.encode('ascii'), client_addr)
        except Exception as e:
            log_manager.error(f"以太网[{self._device_id}]", f"ASCII发送失败: {e}")
            return False

    @staticmethod
    def ping(host: str, count: int = 4, timeout: float = 2.0) -> Tuple[bool, str]:
        try:
            param = '-n' if sys.platform == 'win32' else '-c'
            timeout_param = '-w' if sys.platform == 'win32' else '-W'
            cmd = ['ping', param, str(count), timeout_param, str(int(timeout * 1000)), host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * count + 2)
            output = result.stdout
            if result.returncode == 0:
                return True, output
            return False, output
        except Exception as e:
            return False, str(e)

    @staticmethod
    def scan_port(host: str, port: int, timeout: float = 1.0) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    @staticmethod
    def scan_ports_range(host: str, start_port: int, end_port: int,
                         timeout: float = 1.0) -> List[int]:
        open_ports = []
        for port in range(start_port, end_port + 1):
            if EthernetClient.scan_port(host, port, timeout):
                open_ports.append(port)
        return open_ports

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
                                                  name=f"EthReconnect-{self._device_id}")
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        while self._running is False and self._config.auto_reconnect:
            self._set_state(ConnectionState.RECONNECTING)
            self._reconnect_attempts += 1
            delay = exponential_backoff(self._reconnect_attempts - 1, self._config.reconnect_interval * 0.5,
                                        self._config.reconnect_interval * 10)
            log_manager.info(f"以太网[{self._device_id}]",
                             f"第{self._reconnect_attempts}次尝试重连，延迟{delay:.1f}秒...")
            time.sleep(delay)
            if self.connect():
                return

    def _receive_loop(self):
        while self._running:
            try:
                if self._sock is None:
                    break
                if self._mode == EthernetMode.TCP_CLIENT:
                    ready, _, _ = select.select([self._sock], [], [], 0.5)
                    if ready:
                        if not self._io_lock.acquire(blocking=False):
                            continue
                        try:
                            data = self._sock.recv(4096)
                            if data:
                                self._rx_stats["bytes"] += len(data)
                                self._rx_stats["packets"] += 1
                                if self._on_data_received:
                                    self._on_data_received(data, None)
                            else:
                                log_manager.warn(f"以太网[{self._device_id}]", "TCP连接已断开")
                                self._sock.close()
                                self._sock = None
                                self._set_state(ConnectionState.DISCONNECTED)
                                self._start_reconnect()
                                break
                        finally:
                            self._io_lock.release()
                elif self._mode == EthernetMode.UDP:
                    ready, _, _ = select.select([self._sock], [], [], 0.5)
                    if ready:
                        data, addr = self._sock.recvfrom(4096)
                        self._rx_stats["bytes"] += len(data)
                        self._rx_stats["packets"] += 1
                        if self._on_data_received:
                            self._on_data_received(data, f"{addr[0]}:{addr[1]}")
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                self._rx_stats["errors"] += 1
                log_manager.warn(f"以太网[{self._device_id}]", f"TCP连接已断开: {e}")
                self._running = False
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                self._set_state(ConnectionState.DISCONNECTED)
                self._start_reconnect()
                break
            except Exception as e:
                self._rx_stats["errors"] += 1
                if self._running:
                    log_manager.error(f"以太网[{self._device_id}]", f"接收异常: {e}")
                time.sleep(0.5)

    def _accept_loop(self):
        while self._running:
            try:
                if self._sock is None:
                    break
                ready, _, _ = select.select([self._sock], [], [], 0.5)
                if ready:
                    client_sock, client_addr = self._sock.accept()
                    client_id = f"{client_addr[0]}:{client_addr[1]}"
                    client_sock.setblocking(False)
                    conn = TcpConnection(
                        sock=client_sock,
                        addr=client_addr,
                        connected_at=time.time()
                    )
                    if len(self._clients) >= self._config.max_connections:
                        client_sock.close()
                        log_manager.warn(f"以太网[{self._device_id}]", f"拒绝连接{client_id}: 已达最大连接数")
                        continue
                    self._clients[client_id] = conn
                    log_manager.info(f"以太网[{self._device_id}]", f"客户端{client_id}已连接")
                    if self._on_client_connected:
                        self._on_client_connected(client_id)
                    threading.Thread(target=self._client_receive_loop, args=(client_id, conn),
                                     daemon=True, name=f"EthClientRx-{client_id}").start()
            except Exception as e:
                if self._running:
                    log_manager.error(f"以太网[{self._device_id}]", f"接受连接异常: {e}")
                time.sleep(0.5)

    def _client_receive_loop(self, client_id: str, conn: TcpConnection):
        while self._running and client_id in self._clients:
            try:
                ready, _, _ = select.select([conn.sock], [], [], 0.5)
                if ready:
                    data = conn.sock.recv(4096)
                    if data:
                        conn.rx_bytes += len(data)
                        conn.rx_packets += 1
                        self._rx_stats["bytes"] += len(data)
                        self._rx_stats["packets"] += 1
                        if self._on_data_received:
                            self._on_data_received(data, client_id)
                    else:
                        conn.sock.close()
                        del self._clients[client_id]
                        log_manager.info(f"以太网[{self._device_id}]", f"客户端{client_id}已断开")
                        if self._on_client_disconnected:
                            self._on_client_disconnected(client_id)
                        break
            except Exception:
                if client_id in self._clients:
                    try:
                        conn.sock.close()
                    except Exception:
                        pass
                    del self._clients[client_id]
                    if self._on_client_disconnected:
                        self._on_client_disconnected(client_id)
                break


class EthernetManager:
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
        self._clients: Dict[str, EthernetClient] = {}

    def get_client(self, device_id: str, config: EthernetConfig) -> EthernetClient:
        if device_id in self._clients:
            client = self._clients[device_id]
            client.config = config
            return client
        client = EthernetClient(config, device_id)
        self._clients[device_id] = client
        return client

    def remove_client(self, device_id: str):
        if device_id in self._clients:
            self._clients[device_id].disconnect()
            del self._clients[device_id]

    def connect_device(self, device_id: str, config: EthernetConfig) -> bool:
        client = self.get_client(device_id, config)
        return client.connect()

    def disconnect_device(self, device_id: str):
        if device_id in self._clients:
            self._clients[device_id].disconnect()

    def get_device_state(self, device_id: str) -> ConnectionState:
        if device_id in self._clients:
            return self._clients[device_id].state
        return ConnectionState.DISCONNECTED


ethernet_manager = EthernetManager()