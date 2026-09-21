from abc import ABC, abstractmethod
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass

from config.config_manager import ProtocolConfig, CollectPoint
from core.communication.serial_client import SerialClient
from core.communication.ethernet_client import EthernetClient


@dataclass
class ProtocolResponse:
    success: bool
    data: Any = None
    raw_data: bytes = b''
    error_message: str = ""
    timestamp: float = 0.0


class BaseProtocol(ABC):
    PROTOCOL_NAME = "base"

    def __init__(self, config: ProtocolConfig):
        self._config = config
        self._on_response: Optional[Callable[[ProtocolResponse], None]] = None

    @property
    def config(self) -> ProtocolConfig:
        return self._config

    @config.setter
    def config(self, value: ProtocolConfig):
        self._config = value

    def set_response_callback(self, callback: Callable[[ProtocolResponse], None]):
        self._on_response = callback

    @abstractmethod
    def build_read_command(self, point: CollectPoint) -> bytes:
        pass

    @abstractmethod
    def build_write_command(self, point: CollectPoint, value: Any) -> bytes:
        pass

    @abstractmethod
    def parse_response(self, raw_data: bytes, point: CollectPoint) -> ProtocolResponse:
        pass

    @abstractmethod
    def is_my_protocol(self) -> bool:
        pass

    def build_batch_read_command(self, points: List[CollectPoint]) -> Optional[bytes]:
        return None

    def parse_batch_response(self, raw_data: bytes, points: List[CollectPoint]) -> List[ProtocolResponse]:
        return [ProtocolResponse(success=False, error_message="批量读取不支持") for _ in points]

    def validate_frame(self, raw_data: bytes) -> bool:
        return True

    @classmethod
    def get_protocol_name(cls) -> str:
        return cls.PROTOCOL_NAME


class SerialProtocol(BaseProtocol, ABC):
    @abstractmethod
    def send_and_receive(self, serial_client: SerialClient, command: bytes,
                         timeout: Optional[float] = None) -> ProtocolResponse:
        pass


class EthernetProtocol(BaseProtocol, ABC):
    @abstractmethod
    def send_and_receive(self, ethernet_client: EthernetClient, command: bytes,
                         timeout: Optional[float] = None,
                         client_addr: Optional[str] = None) -> ProtocolResponse:
        pass