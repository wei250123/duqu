import struct
import math
import time
from typing import Union, Optional, Any


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def crc16_ccitt(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x00000001:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


def checksum_xor(data: bytes) -> int:
    result = 0
    for byte in data:
        result ^= byte
    return result


def checksum_sum(data: bytes) -> int:
    return sum(data) & 0xFF


def compute_checksum(data: bytes, method: str) -> int:
    methods = {
        'crc16': crc16_modbus,
        'crc16_modbus': crc16_modbus,
        'crc16_ccitt': crc16_ccitt,
        'crc32': crc32,
        'xor': checksum_xor,
        'sum': checksum_sum
    }
    func = methods.get(method.lower())
    if not func:
        raise ValueError(f"不支持的校验方式: {method}")
    return func(data)


def verify_checksum(data: bytes, expected: int, method: str) -> bool:
    return compute_checksum(data, method) == expected


def bytes_to_hex(data: bytes, separator: str = ' ') -> str:
    return separator.join(f'{b:02X}' for b in data)


def hex_to_bytes(hex_str: str) -> bytes:
    hex_str = hex_str.replace(' ', '').replace('\n', '').replace('\r', '')
    return bytes.fromhex(hex_str)


def convert_endian(data: bytes, byte_order: str = 'big_endian') -> bytes:
    if byte_order == 'big_endian':
        return data
    elif byte_order == 'little_endian':
        return data[::-1]
    elif byte_order == 'big_endian_swap':
        result = bytearray()
        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                result.extend(bytes([data[i + 1], data[i]]))
            else:
                result.append(data[i])
        return bytes(result)
    else:
        return data


def bytes_to_value(data: bytes, data_type: str, byte_order: str = 'big_endian') -> Any:
    be_prefix = '>' if byte_order == 'big_endian' else '<'
    dt = data_type.lower()
    if dt in ('string', 'str'):
        return data.decode('utf-8', errors='replace').rstrip('\x00')
    if dt in ('hex_string', 'hex'):
        return data.hex()
    if dt in ('bool', 'boolean'):
        return data[0] != 0 if len(data) > 0 else False
    if dt == 'bit':
        return int(data[0]) > 0 if len(data) > 0 else 0
    type_map = {
        'int8': (f'{be_prefix}b', 1), 'uint8': (f'{be_prefix}B', 1),
        'int16': (f'{be_prefix}h', 2), 'uint16': (f'{be_prefix}H', 2),
        'int32': (f'{be_prefix}i', 4), 'uint32': (f'{be_prefix}I', 4),
        'int64': (f'{be_prefix}q', 8), 'uint64': (f'{be_prefix}Q', 8),
        'float32': (f'{be_prefix}f', 4), 'float64': (f'{be_prefix}d', 8),
        'int16_ab': ('h', 2), 'uint16_ab': ('H', 2),
        'float32_abcd': ('f', 4), 'float32_cdab': ('f', 4),
        'h': (f'{be_prefix}h', 2), 'H': (f'{be_prefix}H', 2),
        'f': (f'{be_prefix}f', 4), 'F': (f'{be_prefix}f', 4),
        'l': (f'{be_prefix}i', 4), 'L': (f'{be_prefix}I', 4),
    }
    if dt not in type_map:
        raise ValueError(f"不支持的数据类型: {data_type}")
    fmt, size = type_map[dt]
    dt_bytes = data
    if dt in ('int16_ab', 'uint16_ab'):
        if len(dt_bytes) < 2:
            dt_bytes = dt_bytes.ljust(2, b'\x00')
        dt_bytes = bytes([dt_bytes[1], dt_bytes[0]]) if len(dt_bytes) >= 2 else dt_bytes
    if dt in ('float32_abcd', 'float32_cdab'):
        if len(dt_bytes) < 4:
            dt_bytes = dt_bytes.ljust(4, b'\x00')
        if dt == 'float32_cdab':
            dt_bytes = bytes([dt_bytes[2], dt_bytes[3], dt_bytes[0], dt_bytes[1]])
    if len(dt_bytes) < size:
        dt_bytes = dt_bytes.ljust(size, b'\x00')
    return struct.unpack(fmt, dt_bytes[:size])[0]


def value_to_bytes(value: Any, data_type: str, byte_order: str = 'big_endian') -> bytes:
    dt = data_type.lower()
    be_prefix = '>' if byte_order == 'big_endian' else '<'
    if dt in ('string', 'str'):
        return value.encode('utf-8') if isinstance(value, str) else str(value).encode('utf-8')
    if dt in ('hex_string', 'hex'):
        if isinstance(value, str):
            return bytes.fromhex(value)
        return bytes(value)
    if dt in ('bool', 'boolean'):
        return b'\x01' if value else b'\x00'
    if dt == 'bit':
        return b'\x01' if value else b'\x00'
    type_map = {
        'int8': f'{be_prefix}b', 'uint8': f'{be_prefix}B',
        'int16': f'{be_prefix}h', 'uint16': f'{be_prefix}H',
        'int32': f'{be_prefix}i', 'uint32': f'{be_prefix}I',
        'int64': f'{be_prefix}q', 'uint64': f'{be_prefix}Q',
        'float32': f'{be_prefix}f', 'float64': f'{be_prefix}d',
        'int16_ab': '>h', 'uint16_ab': '>H',
        'float32_abcd': '>f', 'float32_cdab': '<f',
        'h': f'{be_prefix}h', 'H': f'{be_prefix}H',
        'f': f'{be_prefix}f', 'F': f'{be_prefix}f',
        'l': f'{be_prefix}i', 'L': f'{be_prefix}I',
    }
    if dt not in type_map:
        raise ValueError(f"不支持的数据类型: {data_type}")
    fmt = type_map[dt]
    return struct.pack(fmt, value)


def extract_bits(value: int, start_bit: int, bit_count: int) -> int:
    mask = ((1 << bit_count) - 1) << start_bit
    return (value & mask) >> start_bit


def apply_scale_offset(value: float, scale: float = 1.0, offset: float = 0.0) -> float:
    return value * scale + offset


def evaluate_formula(value: float, formula: str) -> float:
    import re
    formula_safe = formula.replace('x', str(value))
    formula_safe = re.sub(r'[^0-9+\-*/()., ]', '', formula_safe)
    try:
        return float(eval(formula_safe, {"__builtins__": {}}, {"math": math}))
    except Exception:
        return value


def format_timestamp(dt=None, fmt: str = '%Y-%m-%d %H:%M:%S.%f') -> str:
    from datetime import datetime
    if dt is None:
        return datetime.now().strftime(fmt)[:23]
    if hasattr(dt, 'strftime'):
        return dt.strftime(fmt)[:23]
    return datetime(*dt[:6], microsecond=0).strftime(fmt)[:23]


def is_valid_ip(ip: str) -> bool:
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            num = int(part)
            if num < 0 or num > 255:
                return False
        except ValueError:
            return False
    return True


def is_valid_port(port: int) -> bool:
    return 1 <= port <= 65535


def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    delay = base_delay * (2 ** min(attempt, 10))
    return min(delay, max_delay)