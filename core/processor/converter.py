import struct
import math
from typing import Any, Optional, Union


class DataConverter:
    LINEAR = "linear"
    SCALE_OFFSET = "scale_offset"
    STRING_TO_NUMBER = "string_to_number"
    NUMBER_TO_STRING = "number_to_string"
    TO_BOOLEAN = "to_boolean"
    TO_INTEGER = "to_integer"
    TO_FLOAT = "to_float"
    ROUND = "round"
    ABS = "abs"
    BIT_EXTRACT = "bit_extract"
    ENUM_MAP = "enum_map"
    CLAMP = "clamp"

    @staticmethod
    def convert(value: Any, conversion_type: str, params: Optional[dict] = None) -> Any:
        if value is None:
            return None
        params = params or {}
        method_map = {
            DataConverter.LINEAR: DataConverter._linear,
            DataConverter.SCALE_OFFSET: DataConverter._scale_offset,
            DataConverter.STRING_TO_NUMBER: DataConverter._string_to_number,
            DataConverter.NUMBER_TO_STRING: DataConverter._number_to_string,
            DataConverter.TO_BOOLEAN: DataConverter._to_boolean,
            DataConverter.TO_INTEGER: DataConverter._to_integer,
            DataConverter.TO_FLOAT: DataConverter._to_float,
            DataConverter.ROUND: DataConverter._round_value,
            DataConverter.ABS: DataConverter._abs_value,
            DataConverter.BIT_EXTRACT: DataConverter._bit_extract,
            DataConverter.ENUM_MAP: DataConverter._enum_map,
            DataConverter.CLAMP: DataConverter._clamp,
        }
        handler = method_map.get(conversion_type)
        if handler:
            return handler(value, params)
        return value

    @staticmethod
    def _linear(value: Any, params: dict) -> float:
        k = float(params.get('k', 1.0))
        b = float(params.get('b', 0.0))
        return k * float(value) + b

    @staticmethod
    def _scale_offset(value: Any, params: dict) -> float:
        scale = float(params.get('scale', 1.0))
        offset = float(params.get('offset', 0.0))
        return float(value) * scale + offset

    @staticmethod
    def _string_to_number(value: Any, params: dict) -> Union[int, float]:
        base = int(params.get('base', 10))
        s = str(value).strip()
        if '.' in s:
            return float(s)
        return int(s, base)

    @staticmethod
    def _number_to_string(value: Any, params: dict) -> str:
        fmt = params.get('format', '{}')
        precision = params.get('precision')
        if precision is not None and isinstance(value, float):
            return f"{value:.{precision}f}"
        return fmt.format(value)

    @staticmethod
    def _to_boolean(value: Any, params: dict) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        s = str(value).strip().lower()
        return s in ('true', '1', 'yes', 'on')

    @staticmethod
    def _to_integer(value: Any, params: dict) -> int:
        return int(float(value))

    @staticmethod
    def _to_float(value: Any, params: dict) -> float:
        return float(value)

    @staticmethod
    def _round_value(value: Any, params: dict) -> float:
        decimals = int(params.get('decimals', 2))
        return round(float(value), decimals)

    @staticmethod
    def _abs_value(value: Any, params: dict) -> float:
        return abs(float(value))

    @staticmethod
    def _bit_extract(value: Any, params: dict) -> int:
        bit_pos = int(params.get('bit_position', 0))
        bit_count = int(params.get('bit_count', 1))
        v = int(value)
        mask = ((1 << bit_count) - 1) << bit_pos
        return (v & mask) >> bit_pos

    @staticmethod
    def _enum_map(value: Any, params: dict) -> Any:
        mapping = params.get('mapping', {})
        key = str(value).strip()
        return mapping.get(key, params.get('default', value))

    @staticmethod
    def _clamp(value: Any, params: dict) -> float:
        v = float(value)
        lo = float(params.get('min', float('-inf')))
        hi = float(params.get('max', float('inf')))
        return max(lo, min(v, hi))