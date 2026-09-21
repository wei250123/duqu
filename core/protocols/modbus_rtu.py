import struct
import time
from typing import Optional, List

from config.config_manager import ProtocolConfig, CollectPoint
from core.communication.protocol_base import SerialProtocol, ProtocolResponse
from core.communication.serial_client import SerialClient
from utils.helpers import crc16_modbus, bytes_to_value, bytes_to_hex
from utils.logger import log_manager


class ModbusRTUProtocol(SerialProtocol):
    PROTOCOL_NAME = "modbus_rtu"

    FUNCTION_CODES = {
        'coil': 0x01,
        'discrete_input': 0x02,
        'holding_register': 0x03,
        'input_register': 0x04,
    }

    WRITE_FUNCTION_CODES = {
        'coil': 0x05,
        'holding_register': 0x06,
        'multiple_coils': 0x0F,
        'multiple_registers': 0x10,
    }

    def __init__(self, config: ProtocolConfig):
        super().__init__(config)

    def build_read_command(self, point: CollectPoint) -> bytes:
        func_code = self.FUNCTION_CODES.get(point.register_type, 0x03)
        slave_id = point.get_slave_id(self._config.slave_id)
        addr = point.register_address
        count = max(1, point._get_register_count())
        frame = struct.pack('>BBHH', slave_id, func_code, addr, count)
        crc = crc16_modbus(frame)
        frame += struct.pack('<H', crc)
        return frame

    def build_write_command(self, point: CollectPoint, value) -> bytes:
        slave_id = point.get_slave_id(self._config.slave_id)
        addr = point.register_address
        if point.register_type in ('coil', 'discrete_input'):
            func_code = 0x05
            val = 0xFF00 if value else 0x0000
            frame = struct.pack('>BBHH', slave_id, func_code, addr, val)
        else:
            func_code = 0x06
            val_bytes = self._value_to_register_bytes(value, point.data_type)
            if len(val_bytes) == 2:
                val_int = struct.unpack('>H', val_bytes)[0]
                frame = struct.pack('>BBHH', slave_id, func_code, addr, val_int)
            else:
                func_code = 0x10
                reg_count = len(val_bytes) // 2
                byte_count = len(val_bytes)
                frame = struct.pack('>BBHHB', slave_id, func_code, addr, reg_count, byte_count)
                frame += val_bytes
        crc = crc16_modbus(frame)
        frame += struct.pack('<H', crc)
        return frame

    def parse_response(self, raw_data: bytes, point: CollectPoint) -> ProtocolResponse:
        if len(raw_data) < 5:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="响应数据长度不足", timestamp=time.time())
        crc_received = struct.unpack('<H', raw_data[-2:])[0]
        crc_calc = crc16_modbus(raw_data[:-2])
        if crc_received != crc_calc:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"CRC校验失败: 接收={crc_received:04X}, 计算={crc_calc:04X}",
                                    timestamp=time.time())
        slave_id = raw_data[0]
        func_code = raw_data[1]
        expected_slave = point.get_slave_id(self._config.slave_id)
        if slave_id != expected_slave:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"从站ID不匹配: 期望={expected_slave}, 实际={slave_id}",
                                    timestamp=time.time())
        if func_code & 0x80:
            error_code = raw_data[2] if len(raw_data) > 2 else 0
            error_msgs = {
                0x01: "非法功能码", 0x02: "非法数据地址", 0x03: "非法数据值",
                0x04: "从站设备故障", 0x05: "确认", 0x06: "从站设备忙",
                0x08: "存储奇偶性差错", 0x0A: "网关路径不可用", 0x0B: "网关目标设备响应失败"
            }
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"从站异常: {error_msgs.get(error_code, f'错误码{error_code}')}",
                                    timestamp=time.time())
        byte_count = raw_data[2] if len(raw_data) > 2 else 0
        data_bytes = raw_data[3:3 + byte_count]
        try:
            value = bytes_to_value(data_bytes, point.data_type, point.byte_order)
            return ProtocolResponse(success=True, data=value, raw_data=raw_data, timestamp=time.time())
        except Exception as e:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"数据解析失败: {e}", timestamp=time.time())

    def build_batch_read_command(self, points: List[CollectPoint]) -> Optional[bytes]:
        if not points:
            return None
        from utils.helpers import crc16_modbus
        grouped = {}
        for p in points:
            key = p.register_type
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(p)
        frames = []
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
                    frames.append(self._build_merged_read(reg_type, merged))
                    merged = [p]
            if merged:
                frames.append(self._build_merged_read(reg_type, merged))
        if len(frames) == 1:
            return frames[0]
        return None

    def _build_merged_read(self, reg_type: str, points: List[CollectPoint]) -> bytes:
        func_code = self.FUNCTION_CODES.get(reg_type, 0x03)
        slave_id = points[0].get_slave_id(self._config.slave_id)
        start_addr = points[0].register_address
        total_regs = sum(p._get_register_count() for p in points)
        frame = struct.pack('>BBHH', slave_id, func_code, start_addr, total_regs)
        crc = crc16_modbus(frame)
        frame += struct.pack('<H', crc)
        return frame

    def send_and_receive(self, serial_client: SerialClient, command: bytes,
                         timeout: Optional[float] = None) -> ProtocolResponse:
        timeout = timeout or self._config.response_timeout
        if not serial_client.is_connected:
            return ProtocolResponse(success=False, error_message="串口未连接", timestamp=time.time())
        serial_client._serial.reset_input_buffer()
        serial_client._serial.reset_output_buffer()
        if not serial_client.send(command):
            return ProtocolResponse(success=False, error_message="发送失败", timestamp=time.time())
        time.sleep(0.05)
        response = serial_client.read_until(b'', timeout=timeout)
        if not response:
            return ProtocolResponse(success=False, error_message="响应超时", timestamp=time.time())
        return ProtocolResponse(success=True, data=response, raw_data=response, timestamp=time.time())

    def is_my_protocol(self) -> bool:
        return True

    def _value_to_register_bytes(self, value, data_type: str) -> bytes:
        from utils.helpers import value_to_bytes
        return value_to_bytes(value, data_type, 'big_endian')