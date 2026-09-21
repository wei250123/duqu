import struct
import time
import re
from typing import Optional, Any, Callable

from config.config_manager import ProtocolConfig, CollectPoint
from core.communication.protocol_base import BaseProtocol, ProtocolResponse
from utils.helpers import compute_checksum, bytes_to_hex, hex_to_bytes, bytes_to_value
from utils.logger import log_manager


class CustomProtocol(BaseProtocol):
    PROTOCOL_NAME = "custom"

    def __init__(self, config: ProtocolConfig):
        super().__init__(config)
        self._frame_buffer = bytearray()

    def build_read_command(self, point: CollectPoint) -> bytes:
        frame = bytearray()
        if self._config.custom_start_delimiter:
            start_bytes = self._parse_delimiter(self._config.custom_start_delimiter)
            frame.extend(start_bytes)
        slave_id = point.get_slave_id(self._config.slave_id)
        frame.extend(struct.pack('>B', slave_id))
        func_code = 0x03
        frame.extend(struct.pack('>B', func_code))
        addr = point.register_address
        frame.extend(struct.pack('>H', addr))
        count = 1
        frame.extend(struct.pack('>H', count))
        if self._config.custom_check_method and self._config.custom_check_method != 'none':
            check_value = compute_checksum(bytes(frame), self._config.custom_check_method)
            frame.extend(struct.pack('>H', check_value & 0xFFFF))
        if self._config.custom_end_delimiter:
            end_bytes = self._parse_delimiter(self._config.custom_end_delimiter)
            frame.extend(end_bytes)
        return bytes(frame)

    def build_write_command(self, point: CollectPoint, value: Any) -> bytes:
        frame = bytearray()
        if self._config.custom_start_delimiter:
            start_bytes = self._parse_delimiter(self._config.custom_start_delimiter)
            frame.extend(start_bytes)
        slave_id = point.get_slave_id(self._config.slave_id)
        frame.extend(struct.pack('>B', slave_id))
        func_code = 0x06
        frame.extend(struct.pack('>B', func_code))
        addr = point.register_address
        frame.extend(struct.pack('>H', addr))
        from utils.helpers import value_to_bytes
        val_bytes = value_to_bytes(value, point.data_type, point.byte_order)
        frame.extend(val_bytes)
        if self._config.custom_check_method and self._config.custom_check_method != 'none':
            check_value = compute_checksum(bytes(frame), self._config.custom_check_method)
            frame.extend(struct.pack('>H', check_value & 0xFFFF))
        if self._config.custom_end_delimiter:
            end_bytes = self._parse_delimiter(self._config.custom_end_delimiter)
            frame.extend(end_bytes)
        return bytes(frame)

    def parse_response(self, raw_data: bytes, point: CollectPoint) -> ProtocolResponse:
        import time as _time
        if not raw_data:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="响应数据为空", timestamp=_time.time())
        data = self._extract_frame_data(raw_data)
        if data is None:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="无法解析响应帧", timestamp=_time.time())
        if not self.validate_frame(raw_data):
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message="数据校验失败", timestamp=_time.time())
        try:
            value = bytes_to_value(data, point.data_type, point.byte_order)
            return ProtocolResponse(success=True, data=value, raw_data=raw_data, timestamp=_time.time())
        except Exception as e:
            return ProtocolResponse(success=False, raw_data=raw_data,
                                    error_message=f"数据解析失败: {e}", timestamp=_time.time())

    def validate_frame(self, raw_data: bytes) -> bool:
        if not self._config.custom_check_method or self._config.custom_check_method == 'none':
            return True
        check_len = 2
        if len(raw_data) < check_len + 1:
            return False
        data_for_check = raw_data[:-check_len]
        check_expected = struct.unpack('>H', raw_data[-check_len:])[0]
        check_actual = compute_checksum(data_for_check, self._config.custom_check_method)
        return (check_actual & 0xFFFF) == check_expected

    def is_my_protocol(self) -> bool:
        return True

    def feed_data(self, data: bytes) -> Optional[bytes]:
        self._frame_buffer.extend(data)
        start = self._parse_delimiter(self._config.custom_start_delimiter) if self._config.custom_start_delimiter else None
        end = self._parse_delimiter(self._config.custom_end_delimiter) if self._config.custom_end_delimiter else None
        if start and end:
            buf = bytes(self._frame_buffer)
            start_pos = buf.find(start)
            if start_pos == -1:
                self._frame_buffer.clear()
                return None
            end_pos = buf.find(end, start_pos + len(start))
            if end_pos == -1:
                return None
            frame = buf[start_pos:end_pos + len(end)]
            self._frame_buffer = bytearray(buf[end_pos + len(end):])
            return frame
        return None

    def _extract_frame_data(self, raw_data: bytes) -> Optional[bytes]:
        start = self._parse_delimiter(self._config.custom_start_delimiter) if self._config.custom_start_delimiter else None
        end = self._parse_delimiter(self._config.custom_end_delimiter) if self._config.custom_end_delimiter else None
        data = raw_data
        if start:
            pos = data.find(start)
            if pos >= 0:
                data = data[pos + len(start):]
        if end:
            pos = data.rfind(end)
            if pos >= 0:
                data = data[:pos]
        check_len = 2 if (self._config.custom_check_method and self._config.custom_check_method != 'none') else 0
        if check_len > 0 and len(data) > check_len:
            data = data[:-check_len]
        return bytes(data[:16])

    @staticmethod
    def _parse_delimiter(delimiter: str) -> bytes:
        if not delimiter:
            return b''
        if delimiter.startswith('0x') or delimiter.startswith('0X'):
            return hex_to_bytes(delimiter)
        try:
            return hex_to_bytes(delimiter)
        except Exception:
            return delimiter.encode('ascii')