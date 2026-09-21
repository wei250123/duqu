import struct
import time
from typing import Optional, List

from config.config_manager import ProtocolConfig, CollectPoint
from core.communication.protocol_base import EthernetProtocol, ProtocolResponse
from core.communication.ethernet_client import EthernetClient
from utils.helpers import bytes_to_value
from utils.logger import log_manager


class ModbusTCPProtocol(EthernetProtocol):
    PROTOCOL_NAME = "modbus_tcp"

    FUNCTION_CODES = {
        'coil': 0x01,
        'discrete_input': 0x02,
        'holding_register': 0x03,
        'input_register': 0x04,
    }

    def __init__(self, config: ProtocolConfig):
        super().__init__(config)
        self._transaction_id = 0

    def _next_transaction_id(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    def build_read_command(self, point: CollectPoint) -> bytes:
        func_code = self.FUNCTION_CODES.get(point.register_type, 0x03)
        trans_id = self._next_transaction_id()
        slave_id = point.get_slave_id(self._config.slave_id)
        addr = point.register_address
        count = max(1, point._get_register_count())
        mbap = struct.pack('>HHHBB', trans_id, 0x0000, 0x0006, slave_id, func_code)
        pdu = struct.pack('>HH', addr, count)
        return mbap + pdu

    def build_write_command(self, point: CollectPoint, value) -> bytes:
        trans_id = self._next_transaction_id()
        slave_id = point.get_slave_id(self._config.slave_id)
        addr = point.register_address
        if point.register_type in ('coil', 'discrete_input'):
            func_code = 0x05
            val = 0xFF00 if value else 0x0000
            pdu = struct.pack('>HH', addr, val)
            mbap = struct.pack('>HHHBB', trans_id, 0x0000, 0x0006, slave_id, func_code)
        else:
            func_code = 0x06
            val_bytes = self._value_to_register_bytes(value, point.data_type)
            if len(val_bytes) == 2:
                val_int = struct.unpack('>H', val_bytes)[0]
                pdu = struct.pack('>HH', addr, val_int)
                mbap = struct.pack('>HHHBB', trans_id, 0x0000, 0x0006, slave_id, func_code)
            else:
                func_code = 0x10
                reg_count = len(val_bytes) // 2
                byte_count = len(val_bytes)
                pdu = struct.pack('>HHB', addr, reg_count, byte_count) + val_bytes
                length = 7 + len(val_bytes)
                mbap = struct.pack('>HHHBB', trans_id, 0x0000, length, slave_id, func_code)
        return mbap + pdu

    def parse_response(self, raw_data: bytes, point: CollectPoint) -> ProtocolResponse:
        if len(raw_data) < 9:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="响应数据长度不足", timestamp=time.time())
        trans_id, proto_id, length = struct.unpack('>HHH', raw_data[:6])
        if proto_id != 0:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="协议标识错误", timestamp=time.time())
        slave_id = raw_data[6]
        func_code = raw_data[7]
        if func_code & 0x80:
            error_code = raw_data[8] if len(raw_data) > 8 else 0
            error_msgs = {0x01: "非法功能码", 0x02: "非法数据地址", 0x03: "非法数据值",
                          0x04: "从站设备故障", 0x06: "从站设备忙"}
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"从站异常: {error_msgs.get(error_code, f'错误码{error_code}')}",
                                    timestamp=time.time())
        byte_count = raw_data[8] if len(raw_data) > 8 else 0
        data_bytes = raw_data[9:9 + byte_count]
        try:
            value = bytes_to_value(data_bytes, point.data_type, point.byte_order)
            return ProtocolResponse(success=True, data=value, raw_data=raw_data, timestamp=time.time())
        except Exception as e:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"数据解析失败: {e}", timestamp=time.time())

    def build_batch_read_command(self, points: List[CollectPoint]) -> Optional[bytes]:
        if not points:
            return None
        grouped = {}
        for p in points:
            key = p.register_type
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(p)
        for reg_type, pts in grouped.items():
            pts.sort(key=lambda x: x.register_address)
            merged = [pts[0]]
            for p in pts[1:]:
                last = merged[-1]
                expected_next = last.register_address + last._get_register_count()
                gap = p.register_address - expected_next
                if gap <= 5:
                    merged.append(p)
                else:
                    return self._build_tcp_merged_read(reg_type, merged)
            if merged:
                return self._build_tcp_merged_read(reg_type, merged)
        return None

    def _build_tcp_merged_read(self, reg_type: str, points: List[CollectPoint]) -> bytes:
        func_code = self.FUNCTION_CODES.get(reg_type, 0x03)
        trans_id = self._next_transaction_id()
        slave_id = points[0].get_slave_id(self._config.slave_id)
        start_addr = points[0].register_address
        total_regs = sum(point._get_register_count() for point in points)
        length = 6
        mbap = struct.pack('>HHHBB', trans_id, 0x0000, length, slave_id, func_code)
        pdu = struct.pack('>HH', start_addr, total_regs)
        return mbap + pdu

    def send_and_receive(self, ethernet_client: EthernetClient, command: bytes,
                         timeout: Optional[float] = None,
                         client_addr: Optional[str] = None) -> ProtocolResponse:
        timeout = timeout or self._config.response_timeout
        if not ethernet_client.is_connected:
            return ProtocolResponse(success=False, error_message="网络未连接", timestamp=time.time())
        response = ethernet_client.send_and_receive(command, timeout=timeout)
        if response is None:
            return ProtocolResponse(success=False, error_message="无响应或超时", timestamp=time.time())
        return ProtocolResponse(success=True, data=response, raw_data=response, timestamp=time.time())

    def is_my_protocol(self) -> bool:
        return True

    def _value_to_register_bytes(self, value, data_type: str) -> bytes:
        from utils.helpers import value_to_bytes
        return value_to_bytes(value, data_type, 'big_endian')