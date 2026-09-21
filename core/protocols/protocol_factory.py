from typing import Optional, Dict, Type

from core.communication.protocol_base import BaseProtocol, SerialProtocol, EthernetProtocol
from core.communication.serial_client import SerialClient
from core.communication.ethernet_client import EthernetClient
from core.protocols.modbus_rtu import ModbusRTUProtocol
from core.protocols.modbus_tcp import ModbusTCPProtocol
from core.protocols.modbus_rtu_over_tcp import ModbusRTUOverTCPProtocol
from core.protocols.custom_protocol import CustomProtocol
from config.config_manager import DeviceConfig
from utils.logger import log_manager


class ProtocolFactory:
    _protocol_classes: Dict[str, Type[BaseProtocol]] = {
        'modbus_rtu': ModbusRTUProtocol,
        'modbus_tcp': ModbusTCPProtocol,
        'modbus_rtu_over_tcp': ModbusRTUOverTCPProtocol,
        'custom': CustomProtocol,
    }

    @classmethod
    def register_protocol(cls, name: str, protocol_class: Type[BaseProtocol]):
        cls._protocol_classes[name.lower()] = protocol_class
        log_manager.info("协议工厂", f"已注册协议: {name}")

    @classmethod
    def unregister_protocol(cls, name: str):
        name = name.lower()
        if name in ('modbus_rtu', 'modbus_tcp', 'modbus_rtu_over_tcp', 'custom'):
            return
        cls._protocol_classes.pop(name, None)
        log_manager.info("协议工厂", f"已注销协议: {name}")

    @classmethod
    def get_protocol_names(cls) -> list:
        return list(cls._protocol_classes.keys())

    @classmethod
    def create_protocol(cls, device_config: DeviceConfig) -> Optional[BaseProtocol]:
        protocol_type = device_config.protocol.protocol_type.lower()
        protocol_class = cls._protocol_classes.get(protocol_type)
        if protocol_class is None:
            log_manager.error("协议工厂", f"不支持的协议类型: {protocol_type}")
            return None
        try:
            protocol = protocol_class(device_config.protocol)
            log_manager.info("协议工厂", f"创建协议实例: {protocol_type}")
            return protocol
        except Exception as e:
            log_manager.error("协议工厂", f"创建协议实例失败: {e}")
            return None

    @classmethod
    def create_serial_protocol(cls, device_config: DeviceConfig) -> Optional[SerialProtocol]:
        protocol = cls.create_protocol(device_config)
        if isinstance(protocol, SerialProtocol):
            return protocol
        return None

    @classmethod
    def create_ethernet_protocol(cls, device_config: DeviceConfig) -> Optional[EthernetProtocol]:
        protocol = cls.create_protocol(device_config)
        if isinstance(protocol, EthernetProtocol):
            return protocol
        return None


protocol_factory = ProtocolFactory()