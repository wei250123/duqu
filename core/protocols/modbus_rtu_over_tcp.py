import struct
import time
from typing import Optional, List, Any

from config.config_manager import ProtocolConfig, CollectPoint
from core.communication.protocol_base import EthernetProtocol, ProtocolResponse
from core.communication.ethernet_client import EthernetClient
from core.protocols.modbus_rtu import ModbusRTUProtocol
from utils.helpers import bytes_to_value, crc16_modbus
from utils.logger import log_manager


class ModbusRTUOverTCPProtocol(EthernetProtocol):
    PROTOCOL_NAME = "modbus_rtu_over_tcp"

    def __init__(self, config: ProtocolConfig):
        super().__init__(config)
        self._rtu = ModbusRTUProtocol(config)

    def build_read_command(self, point: CollectPoint) -> bytes:
        return self._rtu.build_read_command(point)

    def build_write_command(self, point: CollectPoint, value: Any) -> bytes:
        return self._rtu.build_write_command(point)

    def build_batch_read_command(self, points: List[CollectPoint]) -> Optional[bytes]:
        return self._rtu.build_batch_read_command(points)

    def parse_response(self, raw_data: bytes, point: CollectPoint) -> ProtocolResponse:
        return self._rtu.parse_response(raw_data, point)

    def is_my_protocol(self) -> bool:
        return True

    def send_and_receive(self, ethernet_client: EthernetClient, command: bytes,
                         timeout: Optional[float] = None,
                         client_addr: Optional[str] = None) -> ProtocolResponse:
        timeout = timeout or self._config.response_timeout
        if not ethernet_client.is_connected:
            return ProtocolResponse(success=False, error_message="网络未连接", timestamp=time.time())
        expect_bytes = 0
        if len(command) >= 4:
            func_code = command[1]
            if func_code in (0x01, 0x02):
                register_count = struct.unpack('>H', command[4:6])[0]
                expect_bytes = 5 + (register_count + 7) // 8
            elif func_code in (0x03, 0x04):
                register_count = struct.unpack('>H', command[4:6])[0]
                expect_bytes = 5 + register_count * 2
            elif func_code == 0x05:
                expect_bytes = 8
            elif func_code == 0x06:
                expect_bytes = 8
        response = ethernet_client.send_and_receive_raw(command, timeout=timeout,
                                                        expect_min_bytes=expect_bytes)
        if response is None:
            return ProtocolResponse(success=False, error_message="无响应或超时",
                                    timestamp=time.time())
        if len(response) < 4:
            return ProtocolResponse(success=False, raw_data=response,
                                    error_message="响应数据长度不足", timestamp=time.time())
        if len(response) > 4:
            crc_received = struct.unpack('<H', response[-2:])[0]
            crc_calc = crc16_modbus(response[:-2])
            if crc_received != crc_calc:
                log_manager.warn(f"ModbusRTUOverTCP",
                                 f"CRC校验失败: 接收={crc_received:04X}, 计算={crc_calc:04X}，继续解析")
        return ProtocolResponse(success=True, data=response, raw_data=response, timestamp=time.time())