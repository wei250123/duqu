import os
import sys
import json
from typing import Any, Dict, List, Optional, Union, get_args, get_origin
from dataclasses import MISSING, dataclass, field, fields


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = get_app_dir()
DATA_DIR = os.path.join(APP_DIR, 'data')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
CONFIG_DIR = os.path.join(DATA_DIR, 'config')
DB_DIR = os.path.join(DATA_DIR, 'db')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')


@dataclass
class SerialConfig:
    port: str = ""
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    flow_control: str = "none"
    timeout: float = 0.3
    auto_reconnect: bool = True
    reconnect_interval: float = 5.0
    reconnect_max_times: int = 0


@dataclass
class EthernetConfig:
    mode: str = "tcp_client"
    host: str = "192.168.1.100"
    port: int = 502
    local_port: int = 0
    timeout: float = 3.0
    auto_reconnect: bool = True
    reconnect_interval: float = 5.0
    max_connections: int = 10


@dataclass  
class ProtocolConfig:
    protocol_type: str = "modbus_rtu"
    slave_id: int = 1
    custom_start_delimiter: str = ""
    custom_end_delimiter: str = ""
    custom_check_method: str = "crc16"
    response_timeout: float = 0.3


@dataclass
class CollectPoint:
    name: str = ""
    description: str = ""
    register_type: str = "holding_register"
    register_address: int = 0
    data_type: str = "uint16"
    byte_order: str = "big_endian"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    alarm_high: Optional[float] = None
    alarm_low: Optional[float] = None
    filter_threshold: Optional[float] = None
    change_rate_filter: Optional[float] = None
    enabled: bool = True
    priority: int = 0
    read_count: int = 0
    slave_id: int = 0

    REGISTER_TYPE_MAP = {
        'coil': 'coil',
        'discrete_input': 'discrete_input',
        'input_register': 'input_register',
        'holding_register': 'holding_register',
    }

    DATA_TYPE_SIZE = {
        'int8': 1, 'uint8': 1, 'boolean': 1, 'bool': 1, 'bit': 1,
        'int16': 2, 'uint16': 2, 'int16_ab': 2, 'uint16_ab': 2,
        'int32': 4, 'uint32': 4, 'float32': 4, 'float32_abcd': 4, 'float32_cdab': 4,
        'int64': 8, 'uint64': 8, 'float64': 8,
        'string': 0, 'hex_string': 0,
        'f': 4, 'h': 2, 'l': 4, 'F': 4, 'H': 2, 'L': 4,
    }

    def _get_register_count(self) -> int:
        if self.read_count > 0:
            return self.read_count
        if self.register_type in ('coil', 'discrete_input'):
            return 1
        byte_size = self.DATA_TYPE_SIZE.get(self.data_type, 2)
        if byte_size == 0:
            return max(1, self.read_count)
        return max(1, (byte_size + 1) // 2)

    def get_slave_id(self, default: int = 1) -> int:
        return self.slave_id if self.slave_id > 0 else default


@dataclass
class CollectConfig:
    mode: str = "timer"
    interval_ms: int = 100
    points: List[CollectPoint] = field(default_factory=list)
    retry_times: int = 3
    retry_interval_ms: int = 100
    timeout_ms: int = 500


@dataclass
class DataFilterConfig:
    enable_threshold: bool = False
    enable_change_rate: bool = False
    enable_null_filter: bool = False
    change_rate_percent: float = 5.0


@dataclass
class DataAggregateConfig:
    enabled: bool = False
    window_seconds: int = 60
    methods: List[str] = field(default_factory=lambda: ["avg"])


@dataclass
class MqttConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    client_id: str = ""
    username: str = ""
    password: str = ""
    use_tls: bool = False
    ca_cert_path: str = ""
    cert_path: str = ""
    key_path: str = ""
    keepalive: int = 60
    qos: int = 1
    retain: bool = False
    topic_prefix: str = "factory/line1"
    will_topic: str = ""
    will_message: str = ""
    will_qos: int = 1
    auto_reconnect: bool = True
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 60.0

@dataclass
class BackupMqttConfig:
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    use_tls: bool = False


@dataclass
class CacheConfig:
    max_records: int = 100000
    max_hours: int = 72
    full_strategy: str = "overwrite_oldest"


class PipelineStage:
    CONVERT = "convert"
    COMPUTE = "compute"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    FUSION = "fusion"
    LUA = "lua"
    TRANSFORM = "transform"
    ENCRYPT = "encrypt"
    CUSTOM = "custom"


@dataclass
class PipelineCondition:
    field: str = "value"
    operator: str = "is_not_none"
    value: Any = None


@dataclass
class PipelineRule:
    name: str = ""
    stage: str = PipelineStage.CONVERT
    enabled: bool = True
    priority: int = 0
    params: dict = field(default_factory=dict)
    point_filter: str = ""
    condition: Optional[dict] = None
    on_fail: str = "continue"
    loop: bool = False
    loop_max: int = 0
    loop_condition: str = ""

    def should_skip(self, result) -> bool:
        if self.point_filter and result.point_name != self.point_filter:
            return True
        if self.condition:
            field_val = getattr(result, self.condition.get('field', 'value'), None)
            op = self.condition.get('operator', 'is_not_none')
            target = self.condition.get('value')
            if op == 'is_none':
                return field_val is not None
            elif op == 'is_not_none':
                return field_val is None
            elif op == 'eq':
                return field_val != target
            elif op == 'neq':
                return field_val == target
            elif op == 'gt':
                return not (field_val is not None and target is not None and float(field_val) > float(target))
            elif op == 'lt':
                return not (field_val is not None and target is not None and float(field_val) < float(target))
            elif op == 'gte':
                return not (field_val is not None and target is not None and float(field_val) >= float(target))
            elif op == 'lte':
                return not (field_val is not None and target is not None and float(field_val) <= float(target))
            elif op == 'in':
                return field_val not in (target if isinstance(target, list) else [target])
            elif op == 'not_in':
                return field_val in (target if isinstance(target, list) else [target])
            elif op == 'between':
                lo = self.condition.get('min')
                hi = self.condition.get('max')
                return not (field_val is not None and lo is not None and hi is not None and lo <= float(field_val) <= hi)
        return False

@dataclass 
class FrontendConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1900
    password: str = "12345678"
    username: str = "admin"

@dataclass
class PipelineConfig:
    enabled: bool = False
    rules: List[PipelineRule] = field(default_factory=list)
    json_template: Optional[dict] = None
    json_schema: Optional[dict] = None
    batch_size: int = 0
    batch_operations: List[dict] = field(default_factory=list)


@dataclass
class LogConfig:
    level: str = "INFO"
    max_file_size_mb: int = 10
    backup_count: int = 30
    save_days: int = 90


@dataclass
class DeviceConfig:
    device_id: str = ""
    name: str = ""
    description: str = ""
    group: str = "default"
    device_type: str = "generic"
    serial: SerialConfig = field(default_factory=SerialConfig)
    ethernet: EthernetConfig = field(default_factory=EthernetConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)
    collect: CollectConfig = field(default_factory=CollectConfig)
    data_filter: DataFilterConfig = field(default_factory=DataFilterConfig)
    data_aggregate: DataAggregateConfig = field(default_factory=DataAggregateConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    backup_mqtt: BackupMqttConfig = field(default_factory=BackupMqttConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    enabled: bool = True


@dataclass
class AppConfig:
    language: str = "zh_CN"
    theme: str = "light"
    font_size: int = 12
    batch_publish: bool = True
    enable_filter: bool = False
    startup_password: str = ""
    startup_password_hash: str = ""
    startup_password_salt: str = ""
    min_to_tray: bool = False
    auto_start_collect: bool = False
    max_upload_rate: int = 0
    log: LogConfig = field(default_factory=LogConfig)
    backup_servers: List[BackupMqttConfig] = field(default_factory=list)


def _dataclass_to_dict(obj) -> dict:
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            result[field_name] = _dataclass_to_dict(value)
        return result
    elif isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    else:
        return obj


def _convert_dataclass_value(value: Any, field_type: Any) -> Any:
    """Convert nested dataclasses while leaving scalar and untyped values unchanged."""
    if value is None:
        return None

    origin = get_origin(field_type)
    args = get_args(field_type)

    if origin in (list, List):
        item_type = args[0] if args else Any
        return [_convert_dataclass_value(item, item_type) for item in value]

    if origin in (dict, Dict):
        value_type = args[1] if len(args) > 1 else Any
        return {
            key: _convert_dataclass_value(item, value_type)
            for key, item in value.items()
        }

    if origin is Union:
        for option in args:
            if option is type(None):
                continue
            converted = _convert_dataclass_value(value, option)
            if converted is not value or hasattr(option, '__dataclass_fields__'):
                return converted
        return value

    if hasattr(field_type, '__dataclass_fields__') and isinstance(value, dict):
        return _dict_to_dataclass(value, field_type)
    return value


def _dict_to_dataclass(data: dict, dataclass_type):
    if not hasattr(dataclass_type, '__dataclass_fields__'):
        return data
    if not isinstance(data, dict):
        raise TypeError(f"Expected object for {dataclass_type.__name__}, got {type(data).__name__}")

    kwargs = {}
    for field_def in fields(dataclass_type):
        field_name = field_def.name
        if field_name in data:
            kwargs[field_name] = _convert_dataclass_value(data[field_name], field_def.type)
        elif field_def.default is not MISSING:
            kwargs[field_name] = field_def.default
        elif field_def.default_factory is not MISSING:
            kwargs[field_name] = field_def.default_factory()

    return dataclass_type(**kwargs)


class ConfigManager:
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
        self._app_config: AppConfig = AppConfig()
        self._devices: Dict[str, DeviceConfig] = {}
        self._config_file = os.path.join(CONFIG_DIR, 'app_config.json')
        self._devices_file = os.path.join(CONFIG_DIR, 'devices.json')
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(DB_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._load()

    @property
    def app_config(self) -> AppConfig:
        return self._app_config

    @property
    def devices(self) -> Dict[str, DeviceConfig]:
        return self._devices

    def get_device(self, device_id: str) -> Optional[DeviceConfig]:
        return self._devices.get(device_id)

    def add_device(self, device: DeviceConfig) -> bool:
        if device.device_id in self._devices:
            return False
        self._devices[device.device_id] = device
        self._save_devices()
        return True

    def update_device(self, device: DeviceConfig) -> bool:
        if device.device_id not in self._devices:
            return False
        self._devices[device.device_id] = device
        self._save_devices()
        return True

    def remove_device(self, device_id: str) -> bool:
        if device_id not in self._devices:
            return False
        del self._devices[device_id]
        self._save_devices()
        return True

    def get_devices_by_group(self, group: str) -> List[DeviceConfig]:
        return [d for d in self._devices.values() if d.group == group]

    def get_all_groups(self) -> List[str]:
        groups = set(d.group for d in self._devices.values())
        return sorted(groups)

    def save_app_config(self):
        data = _dataclass_to_dict(self._app_config)
        with open(self._config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_all(self):
        self.save_app_config()
        self._save_devices()

    def export_config(self, filepath: str):
        data = {
            'app_config': _dataclass_to_dict(self._app_config),
            'devices': {k: _dataclass_to_dict(v) for k, v in self._devices.items()}
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_config(self, filepath: str):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'app_config' in data:
            self._app_config = _dict_to_dataclass(data['app_config'], AppConfig)
        if 'devices' in data:
            self._devices = {}
            for device_id, device_data in data['devices'].items():
                self._devices[device_id] = _dict_to_dataclass(device_data, DeviceConfig)
        self.save_all()

    def restore_defaults(self):
        self._app_config = AppConfig()
        self._devices = {}
        self.save_all()

    def export_device_template(self, device_id: str, filepath: str) -> bool:
        device = self._devices.get(device_id)
        if not device:
            return False
        data = _dataclass_to_dict(device)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def import_device_template(self, filepath: str) -> Optional[DeviceConfig]:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        device = _dict_to_dataclass(data, DeviceConfig)
        return device

    def _save_devices(self):
        data = {k: _dataclass_to_dict(v) for k, v in self._devices.items()}
        with open(self._devices_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._app_config = _dict_to_dataclass(data, AppConfig)
            except Exception:
                self._app_config = AppConfig()
        if os.path.exists(self._devices_file):
            try:
                with open(self._devices_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._devices = {}
                for device_id, device_data in data.items():
                    self._devices[device_id] = _dict_to_dataclass(device_data, DeviceConfig)
            except Exception:
                self._devices = {}


config_manager = ConfigManager()
