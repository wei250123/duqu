import math
from typing import Any, Optional


class DataComputation:
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MODULO = "modulo"
    POWER = "power"
    SQRT = "sqrt"
    LOG = "log"
    LOG10 = "log10"
    EXP = "exp"
    SIN = "sin"
    COS = "cos"
    TAN = "tan"
    ASIN = "asin"
    ACOS = "acos"
    ATAN = "atan"
    DEG2RAD = "deg2rad"
    RAD2DEG = "rad2deg"
    LINEAR_FORMULA = "linear_formula"
    UNIT_CONVERT = "unit_convert"
    EXPRESSION = "expression"

    @staticmethod
    def compute(value: Any, op_type: str, params: Optional[dict] = None) -> Optional[float]:
        if value is None:
            return None
        params = params or {}
        method_map = {
            DataComputation.ADD: lambda v, p: float(v) + float(p.get('operand', 0)),
            DataComputation.SUBTRACT: lambda v, p: float(v) - float(p.get('operand', 0)),
            DataComputation.MULTIPLY: lambda v, p: float(v) * float(p.get('operand', 1)),
            DataComputation.DIVIDE: lambda v, p: float(v) / float(p.get('operand', 1)) if float(p.get('operand', 1)) != 0 else None,
            DataComputation.MODULO: lambda v, p: float(v) % float(p.get('operand', 1)),
            DataComputation.POWER: lambda v, p: float(v) ** float(p.get('operand', 2)),
            DataComputation.SQRT: lambda v, p: math.sqrt(float(v)) if float(v) >= 0 else None,
            DataComputation.LOG: lambda v, p: math.log(float(v)) if float(v) > 0 else None,
            DataComputation.LOG10: lambda v, p: math.log10(float(v)) if float(v) > 0 else None,
            DataComputation.EXP: lambda v, p: math.exp(float(v)),
            DataComputation.SIN: lambda v, p: math.sin(float(v)),
            DataComputation.COS: lambda v, p: math.cos(float(v)),
            DataComputation.TAN: lambda v, p: math.tan(float(v)),
            DataComputation.ASIN: lambda v, p: math.asin(max(-1, min(1, float(v)))),
            DataComputation.ACOS: lambda v, p: math.acos(max(-1, min(1, float(v)))),
            DataComputation.ATAN: lambda v, p: math.atan(float(v)),
            DataComputation.DEG2RAD: lambda v, p: math.radians(float(v)),
            DataComputation.RAD2DEG: lambda v, p: math.degrees(float(v)),
            DataComputation.LINEAR_FORMULA: DataComputation._linear_formula,
            DataComputation.UNIT_CONVERT: DataComputation._unit_convert,
            DataComputation.EXPRESSION: DataComputation._expression,
        }
        handler = method_map.get(op_type)
        if handler:
            try:
                return handler(value, params)
            except (ValueError, TypeError, ZeroDivisionError):
                return None
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _linear_formula(value: Any, params: dict) -> Optional[float]:
        k = float(params.get('k', 1.0))
        b = float(params.get('b', 0.0))
        return k * float(value) + b

    @staticmethod
    def _unit_convert(value: Any, params: dict) -> Optional[float]:
        factor = float(params.get('factor', 1.0))
        return float(value) * factor

    @staticmethod
    def _expression(value: Any, params: dict) -> Optional[float]:
        expr = params.get('expr', 'x')
        x = float(value)
        allowed_names = {
            'x': x, 'y': x, 'pi': math.pi, 'e': math.e,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10,
            'abs': abs, 'round': round, 'floor': math.floor, 'ceil': math.ceil,
            'pow': pow, 'mod': lambda a, b: a % b,
        }
        try:
            result = eval(expr, {'__builtins__': {}}, allowed_names)
            return float(result) if result is not None else None
        except Exception:
            return None

    _UNIT_FACTORS = {
        ('m', 'mm'): 1000, ('m', 'cm'): 100, ('m', 'km'): 0.001,
        ('mm', 'm'): 0.001, ('mm', 'cm'): 0.1,
        ('cm', 'm'): 0.01, ('cm', 'mm'): 10,
        ('km', 'm'): 1000,
        ('kg', 'g'): 1000, ('g', 'kg'): 0.001,
        ('t', 'kg'): 1000, ('kg', 't'): 0.001,
        ('h', 's'): 3600, ('s', 'h'): 1/3600,
        ('min', 's'): 60, ('s', 'min'): 1/60,
        ('h', 'min'): 60, ('min', 'h'): 1/60,
        ('V', 'mV'): 1000, ('mV', 'V'): 0.001,
        ('A', 'mA'): 1000, ('mA', 'A'): 0.001,
        ('W', 'kW'): 0.001, ('kW', 'W'): 1000,
        ('Hz', 'kHz'): 0.001, ('kHz', 'Hz'): 1000,
        ('Pa', 'kPa'): 0.001, ('kPa', 'Pa'): 1000,
        ('Pa', 'MPa'): 0.000001, ('MPa', 'Pa'): 1000000,
        ('°C', '°F'): None,
    }

    @staticmethod
    def get_unit_factor(from_unit: str, to_unit: str) -> Optional[float]:
        if from_unit == to_unit:
            return 1.0
        if from_unit == '°C' and to_unit == '°F':
            return None
        return DataComputation._UNIT_FACTORS.get((from_unit, to_unit))

    @staticmethod
    def convert_unit(value: float, from_unit: str, to_unit: str) -> Optional[float]:
        if from_unit == to_unit:
            return value
        if from_unit == '°C' and to_unit == '°F':
            return value * 9/5 + 32
        if from_unit == '°F' and to_unit == '°C':
            return (value - 32) * 5/9
        factor = DataComputation.get_unit_factor(from_unit, to_unit)
        if factor is not None:
            return value * factor
        return None