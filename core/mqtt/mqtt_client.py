import time
import ssl
import threading
import json
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

import paho.mqtt.client as mqtt
import paho.mqtt

from config.config_manager import MqttConfig, BackupMqttConfig
from utils.logger import log_manager
from utils.helpers import exponential_backoff
from core.storage.cache_manager import cache_manager


class MqttState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class MqttClient:
    def __init__(self, config: MqttConfig, device_id: str = ""):
        self._config = config
        self._device_id = device_id
        self._state = MqttState.DISCONNECTED
        self._client: Optional[mqtt.Client] = None
        self._on_connected: Optional[Callable[[], None]] = None
        self._on_disconnected: Optional[Callable[[], None]] = None
        self._on_message: Optional[Callable[[str, str], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._reconnect_attempts = 0
        self._upload_stats = {"success": 0, "fail": 0, "total": 0}
        self._topic_prefix = ""
        self._is_paho_v2 = self._detect_paho_v2()

    @staticmethod
    def _detect_paho_v2() -> bool:
        try:
            ver = tuple(int(x) for x in paho.mqtt.__version__.split('.')[:2])
            return ver[0] >= 2
        except Exception:
            return False

    def set_connected_callback(self, callback: Callable[[], None]):
        self._on_connected = callback

    def set_disconnected_callback(self, callback: Callable[[], None]):
        self._on_disconnected = callback

    def set_message_callback(self, callback: Callable[[str, str], None]):
        self._on_message = callback

    def set_error_callback(self, callback: Callable[[str], None]):
        self._on_error = callback

    @property
    def state(self) -> MqttState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == MqttState.CONNECTED and self._client is not None

    @property
    def config(self) -> MqttConfig:
        return self._config

    @config.setter
    def config(self, value: MqttConfig):
        self._config = value

    @property
    def stats(self) -> dict:
        return dict(self._upload_stats)

    def reset_stats(self):
        self._upload_stats = {"success": 0, "fail": 0, "total": 0}

    def _build_tls_context(self) -> ssl.SSLContext:
        """Build a verifying TLS context; never silently disable certificate checks."""
        context = ssl.create_default_context()
        if self._config.ca_cert_path and self._config.ca_cert_path.strip():
            context.load_verify_locations(self._config.ca_cert_path)
        if self._config.cert_path and self._config.key_path:
            context.load_cert_chain(self._config.cert_path, self._config.key_path)
        return context

    def connect(self, wait_timeout: float = 5.0) -> bool:
        if self._state == MqttState.CONNECTED:
            return True
        self._cleanup_old_client()
        self._set_state(MqttState.CONNECTING)
        try:
            client_id = self._config.client_id or f"iiot_gateway_{self._device_id}_{int(time.time() * 1000)}"
            proto = mqtt.MQTTv311
            self._client = mqtt.Client(client_id=client_id, protocol=proto, clean_session=True)
            self._client.on_connect = self._on_mqtt_connect
            self._client.on_disconnect = self._on_mqtt_disconnect
            self._client.on_message = self._on_mqtt_message
            self._client.on_publish = self._on_mqtt_publish
            if self._config.username:
                self._client.username_pw_set(self._config.username, self._config.password)
            if self._config.use_tls:
                self._client.tls_set_context(self._build_tls_context())
            if self._config.will_topic:
                self._client.will_set(
                    topic=self._config.will_topic,
                    payload=self._config.will_message,
                    qos=self._config.will_qos,
                    retain=True
                )
            if self._is_paho_v2:
                self._client.loop_start()
                self._client.connect_async(self._config.host, self._config.port, self._config.keepalive)
            else:
                self._client.connect(self._config.host, self._config.port, self._config.keepalive)
                self._client.loop_start()
            log_manager.info(f"MQTT[{self._device_id}]",
                            f"正在连接 {self._config.host}:{self._config.port} [paho-mqtt={paho.mqtt.__version__}]")
            deadline = time.time() + wait_timeout
            while time.time() < deadline:
                if self._state == MqttState.CONNECTED:
                    self._reconnect_attempts = 0
                    self._run_connectivity_test()
                    return True
                if self._state == MqttState.ERROR:
                    return False
                time.sleep(0.1)
            self._set_state(MqttState.ERROR)
            log_manager.warn(f"MQTT[{self._device_id}]", f"连接超时 (>{wait_timeout}s)")
            return False
        except Exception as e:
            self._set_state(MqttState.ERROR)
            log_manager.error(f"MQTT[{self._device_id}]", f"连接失败: {e}")
            return False

    def _cleanup_old_client(self):
        if self._client is None:
            return
        try:
            self._client.loop_stop()
        except Exception:
            pass
        try:
            self._client.disconnect()
        except Exception:
            pass
        self._client = None

    def disconnect(self):
        self._cleanup_old_client()
        self._set_state(MqttState.DISCONNECTED)
        log_manager.info(f"MQTT[{self._device_id}]", "已断开连接")

    def publish(self, topic: str, payload: str, qos: Optional[int] = None,
                retain: Optional[bool] = None) -> bool:
        if not self.is_connected:
            log_manager.warn(f"MQTT[{self._device_id}]", f"发布失败: 未连接, 数据已缓存")
            cache_manager.cache_data(self._device_id, topic, payload, qos or self._config.qos)
            self._upload_stats["fail"] += 1
            self._upload_stats["total"] += 1
            return False
        try:
            result = self._client.publish(
                topic=topic,
                payload=payload,
                qos=qos if qos is not None else self._config.qos,
                retain=retain if retain is not None else self._config.retain
            )
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self._upload_stats["success"] += 1
                self._upload_stats["total"] += 1
                payload_preview = (payload[:200] + '...') if len(payload) > 200 else payload
                log_manager.info(f"MQTT[{self._device_id}]",
                                f"发布入队: {topic} [qos={qos or self._config.qos}] mid={result.mid} payload={payload_preview}")
                return True
            else:
                self._upload_stats["fail"] += 1
                self._upload_stats["total"] += 1
                log_manager.warn(f"MQTT[{self._device_id}]", f"发布失败: rc={result.rc}, topic={topic}")
                return False
        except Exception as e:
            self._upload_stats["fail"] += 1
            self._upload_stats["total"] += 1
            log_manager.error(f"MQTT[{self._device_id}]", f"发布异常: {e}, topic={topic}")
            cache_manager.cache_data(self._device_id, topic, payload, qos or self._config.qos)
            return False

    def publish_json(self, topic: str, data: dict, qos: Optional[int] = None,
                     retain: Optional[bool] = None) -> bool:
        payload = json.dumps(data, ensure_ascii=False)
        return self.publish(topic, payload, qos, retain)

    def subscribe(self, topic: str, qos: int = 0) -> bool:
        if not self.is_connected:
            return False
        try:
            result = self._client.subscribe(topic, qos)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                log_manager.info(f"MQTT[{self._device_id}]", f"已订阅: {topic}")
                return True
            return False
        except Exception as e:
            log_manager.error(f"MQTT[{self._device_id}]", f"订阅失败: {e}")
            return False

    def unsubscribe(self, topic: str):
        if self.is_connected:
            try:
                self._client.unsubscribe(topic)
                log_manager.info(f"MQTT[{self._device_id}]", f"已取消订阅: {topic}")
            except Exception as e:
                log_manager.error(f"MQTT[{self._device_id}]", f"取消订阅失败: {e}")

    def get_topic(self, data_type: str = "telemetry", point_name: str = "") -> str:
        prefix = self._config.topic_prefix or "factory/line1"
        parts = [prefix]
        if self._device_id:
            parts.append(self._device_id)
        parts.append(data_type)
        if point_name:
            parts.append(point_name)
        return '/'.join(parts)

    def _set_state(self, state: MqttState):
        if self._state != state:
            self._state = state

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._set_state(MqttState.CONNECTED)
            log_manager.info(f"MQTT[{self._device_id}]", f"已连接到 {self._config.host}:{self._config.port}")
            if self._on_connected:
                try:
                    self._on_connected()
                except Exception:
                    pass
        else:
            error_msgs = {
                1: "协议版本错误", 2: "客户端ID被拒绝", 3: "服务器不可用",
                4: "用户名或密码错误", 5: "未授权"
            }
            self._set_state(MqttState.ERROR)
            msg = error_msgs.get(rc, f"未知错误({rc})")
            log_manager.error(f"MQTT[{self._device_id}]", f"连接失败: {msg}")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        if rc != 0:
            log_manager.warn(f"MQTT[{self._device_id}]", f"意外断开连接: rc={rc}")
            self._set_state(MqttState.DISCONNECTED)
            if self._on_disconnected:
                try:
                    self._on_disconnected()
                except Exception:
                    pass
            if self._config.auto_reconnect:
                self._schedule_reconnect()

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
            log_manager.debug(f"MQTT[{self._device_id}]", f"收到消息: {msg.topic} -> {payload[:100]}")
            if self._on_message:
                self._on_message(msg.topic, payload)
        except Exception as e:
            log_manager.error(f"MQTT[{self._device_id}]", f"处理消息失败: {e}")

    def _on_mqtt_publish(self, client, userdata, mid):
        log_manager.info(f"MQTT[{self._device_id}]", f"PUBACK确认: mid={mid} (broker已收到)")

    def _run_connectivity_test(self):
        test_topic = f"{self._config.topic_prefix or 'factory/line1'}/__test__/connectivity"
        test_payload = json.dumps({"device_id": self._device_id, "msg": "connectivity_test",
                                   "ts": time.time()})
        log_manager.info(f"MQTT[{self._device_id}]", f"连接自检: 发布测试消息到 {test_topic}")
        self._client.publish(test_topic, test_payload, qos=1)

    def _schedule_reconnect(self):
        if self._state == MqttState.RECONNECTING:
            return
        self._set_state(MqttState.RECONNECTING)
        threading.Thread(target=self._reconnect_loop, daemon=True,
                         name=f"MqttReconnect-{self._device_id}").start()

    def _reconnect_loop(self):
        while self._config.auto_reconnect:
            if self._state not in (MqttState.RECONNECTING, MqttState.ERROR):
                return
            self._reconnect_attempts += 1
            delay = exponential_backoff(
                self._reconnect_attempts - 1,
                self._config.reconnect_min_delay,
                self._config.reconnect_max_delay
            )
            log_manager.info(f"MQTT[{self._device_id}]",
                             f"第{self._reconnect_attempts}次重连，延迟{delay:.1f}秒...")
            time.sleep(delay)
            self._set_state(MqttState.RECONNECTING)
            if self.connect():
                return

class MqttManager:
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
        self._clients: Dict[str, MqttClient] = {}
        self._backup_configs: Dict[str, BackupMqttConfig] = {}
        self._using_backup: Dict[str, bool] = {}

    def get_client(self, device_id: str, config: Optional[MqttConfig] = None) -> MqttClient:
        if device_id in self._clients:
            client = self._clients[device_id]
            if config:
                client.config = config
            return client
        if config is None:
            config = MqttConfig()
        client = MqttClient(config, device_id)
        self._clients[device_id] = client
        return client

    def remove_client(self, device_id: str):
        if device_id in self._clients:
            self._clients[device_id].disconnect()
            del self._clients[device_id]
            self._backup_configs.pop(device_id, None)

    def set_backup(self, device_id: str, backup_config: BackupMqttConfig):
        self._backup_configs[device_id] = backup_config

    def connect_device(self, device_id: str, config: MqttConfig) -> bool:
        client = self.get_client(device_id, config)
        cache_manager.register_device(device_id, config.cache if hasattr(config, 'cache') else None,
                                      lambda records: self._cache_upload_callback(device_id, records))
        success = client.connect()
        if not success and config.auto_reconnect:
            client._schedule_reconnect()
        return success

    def disconnect_device(self, device_id: str):
        if device_id in self._clients:
            self._clients[device_id].disconnect()

    def get_device_state(self, device_id: str) -> MqttState:
        if device_id in self._clients:
            return self._clients[device_id].state
        return MqttState.DISCONNECTED

    def publish(self, device_id: str, topic: str, payload: str, qos: Optional[int] = None) -> bool:
        client = self._clients.get(device_id)
        if not client:
            return False
        success = client.publish(topic, payload, qos)
        if not success:
            self._try_backup(device_id, topic, payload, qos)
        return success

    def publish_json(self, device_id: str, topic: str, data: dict,
                     qos: Optional[int] = None) -> bool:
        client = self._clients.get(device_id)
        if not client:
            return False
        success = client.publish_json(topic, data, qos)
        if not success:
            payload = json.dumps(data, ensure_ascii=False)
            self._try_backup(device_id, topic, payload, qos)
        return success

    def _try_backup(self, device_id: str, topic: str, payload: str, qos: Optional[int] = None):
        backup = self._backup_configs.get(device_id)
        if not backup or not backup.host:
            return
        if self._using_backup.get(device_id):
            return
        try:
            log_manager.info(f"MQTT[{device_id}]", f"尝试备用服务器 {backup.host}:{backup.port}")
            backup_config = MqttConfig(
                host=backup.host,
                port=backup.port,
                username=backup.username,
                password=backup.password,
                use_tls=backup.use_tls,
                auto_reconnect=False
            )
            temp_client = MqttClient(backup_config, f"{device_id}_backup")
            if temp_client.connect():
                import time as _time
                _time.sleep(0.5)
                temp_client.publish(topic, payload, qos)
                temp_client.disconnect()
                self._using_backup[device_id] = True
                log_manager.info(f"MQTT[{device_id}]", f"已通过备用服务器发送数据")
        except Exception as e:
            log_manager.error(f"MQTT[{device_id}]", f"备用服务器发送失败: {e}")

    def _cache_upload_callback(self, device_id: str, records: List[Dict]) -> bool:
        client = self._clients.get(device_id)
        if not client or not client.is_connected:
            return False
        all_success = True
        for record in records:
            success = client.publish(record['topic'], record['payload'], record['qos'])
            if not success:
                all_success = False
        return all_success

    def get_all_status(self) -> Dict[str, dict]:
        status = {}
        for device_id, client in self._clients.items():
            status[device_id] = {
                'state': client.state.value,
                'is_connected': client.is_connected,
                'stats': client.stats,
                'using_backup': self._using_backup.get(device_id, False)
            }
        return status


mqtt_manager = MqttManager()
