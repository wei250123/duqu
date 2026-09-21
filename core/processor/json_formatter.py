import json
import time
import hashlib
import struct
from typing import Any, Dict, List, Optional, Union

from core.data_types import CollectResult
from core.security.encryption import data_encryptor


class JsonFormatter:
    def __init__(self, device_id: str = "", data_version: str = "1.0.0",
                 gateway_id: str = "IIoTGateway-001"):
        self._device_id = device_id
        self._data_version = data_version
        self._gateway_id = gateway_id
        self._schema = None

    def set_schema(self, schema: dict):
        self._schema = schema

    def format_single(self, result: CollectResult, custom_template: Optional[dict] = None,
                      include_meta: bool = True) -> dict:
        if custom_template:
            return self._apply_template(result, custom_template, include_meta)
        return self._build_default_single(result, include_meta)

    def format_batch(self, results: List[CollectResult], custom_template: Optional[dict] = None,
                     batch_size: int = 0) -> Union[dict, List[dict]]:
        if batch_size > 0:
            batches = []
            for i in range(0, len(results), batch_size):
                chunk = results[i:i + batch_size]
                batches.append(self._build_batch(chunk, custom_template))
            return batches
        return self._build_batch(results, custom_template)

    def format_batch_array(self, results: List[CollectResult],
                           custom_template: Optional[dict] = None) -> List[dict]:
        items = []
        for r in results:
            if custom_template:
                items.append(self._apply_template(r, custom_template, True))
            else:
                items.append(self._build_default_single(r, True))
        return items

    def _build_default_single(self, result: CollectResult,
                              include_meta: bool = True) -> dict:
        data = {
            'point_name': result.point_name,
            'point_description': result.point_description,
            'value': result.value,
            'raw_value': result.raw_value,
            'unit': result.unit,
            'success': result.success,
            'is_alarm': result.is_alarm,
            'error_message': result.error_message,
        }
        if include_meta:
            data['meta'] = self._build_metadata(result)
        if result.is_alarm:
            data['alarm_info'] = {
                'alarm_high': result.alarm_high,
                'alarm_low': result.alarm_low,
            }
        return data

    def _build_metadata(self, result: CollectResult) -> dict:
        return {
            'device_id': result.device_id or self._device_id,
            'timestamp': self._to_iso8601(result.timestamp),
            'timestamp_ms': int(result.timestamp * 1000) if result.timestamp else 0,
            'data_version': self._data_version,
            'gateway_id': self._gateway_id,
            'gateway_status': 'running',
            'sequence': int(time.time() * 1000) % 1000000,
        }

    def _build_batch(self, results: List[CollectResult],
                     custom_template: Optional[dict] = None) -> dict:
        now = time.time()
        values = []
        alarms = []
        success_count = 0
        fail_count = 0
        for r in results:
            if custom_template:
                values.append(self._apply_template(r, custom_template, False))
            else:
                values.append(self._build_default_single(r, False))
            if r.success:
                success_count += 1
            else:
                fail_count += 1
            if r.is_alarm:
                alarms.append({
                    'point_name': r.point_name,
                    'value': r.value,
                    'unit': r.unit,
                    'alarm_high': r.alarm_high,
                    'alarm_low': r.alarm_low,
                })
        batch = {
            'meta': {
                'device_id': self._device_id,
                'timestamp': self._to_iso8601(now),
                'timestamp_ms': int(now * 1000),
                'data_version': self._data_version,
                'gateway_id': self._gateway_id,
                'gateway_status': 'running',
                'batch_count': len(values),
                'batch_hash': self._compute_hash(values),
            },
            'stats': {
                'total': len(results),
                'success': success_count,
                'fail': fail_count,
                'success_rate': round(success_count / max(len(results), 1) * 100, 2),
            },
            'values': values,
            'alarms': alarms,
        }
        return batch

    def _apply_template(self, result: CollectResult, template: dict,
                        include_meta: bool = True) -> dict:
        data = {}
        for key, path in template.items():
            if key == '$meta' and include_meta:
                data[key] = self._build_metadata(result)
            elif isinstance(path, dict):
                data[key] = self._resolve_template_value(path, result)
            elif isinstance(path, str) and path.startswith('$'):
                data[key] = self._resolve_ref(path, result)
            elif isinstance(path, list):
                data[key] = [self._resolve_template_value(item, result)
                             if isinstance(item, dict)
                             else self._resolve_ref(item, result)
                             if isinstance(item, str) and item.startswith('$')
                             else item
                             for item in path]
            else:
                data[key] = path
        if include_meta:
            data['meta'] = self._build_metadata(result)
        return data

    def _resolve_template_value(self, value_def: dict, result: CollectResult) -> Any:
        if 'value' not in value_def:
            return {k: self._resolve_template_value(v, result)
                    if isinstance(v, dict) else v
                    for k, v in value_def.items()}
        ref = value_def.get('value', '')
        val = self._resolve_ref(ref, result)
        convert = value_def.get('convert')
        if convert:
            val = self._apply_conversion(val, convert)
        encrypt = value_def.get('encrypt', False)
        if encrypt:
            val = data_encryptor.encrypt(str(val))
        fmt = value_def.get('format')
        if fmt and isinstance(val, (int, float)):
            val = f"{val:{fmt}}"
        return val

    def _resolve_ref(self, ref: str, result: CollectResult) -> Any:
        ref_map = {
            '$device_id': result.device_id or self._device_id,
            '$point_name': result.point_name,
            '$point_description': result.point_description,
            '$value': result.value,
            '$raw_value': result.raw_value,
            '$unit': result.unit,
            '$success': result.success,
            '$is_alarm': result.is_alarm,
            '$error_message': result.error_message,
            '$timestamp': self._to_iso8601(result.timestamp),
            '$timestamp_ms': int(result.timestamp * 1000) if result.timestamp else 0,
            '$alarm_high': result.alarm_high or '',
            '$alarm_low': result.alarm_low or '',
            '$gateway_id': self._gateway_id,
            '$data_version': self._data_version,
        }
        return ref_map.get(ref, ref)

    def _apply_conversion(self, value: Any, convert: str) -> Any:
        if value is None:
            return None
        try:
            if convert == 'string':
                return str(value)
            elif convert == 'int':
                return int(float(value))
            elif convert == 'float':
                return float(value)
            elif convert == 'bool':
                return bool(value)
            elif convert == 'hex':
                if isinstance(value, int):
                    return hex(value)
                return value
            elif convert == 'bin':
                if isinstance(value, int):
                    return bin(value)
                return value
            elif convert == 'base64':
                import base64
                return base64.b64encode(str(value).encode()).decode()
            elif convert == 'upper':
                return str(value).upper()
            elif convert == 'lower':
                return str(value).lower()
            return value
        except Exception:
            return value

    def to_json(self, data: Any, indent: Optional[int] = None) -> str:
        return json.dumps(data, ensure_ascii=False, indent=indent,
                          separators=(',', ':') if indent is None else None,
                          allow_nan=False)

    def validate_schema(self, data: dict) -> bool:
        if not self._schema:
            return True
        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=self._schema)
            return True
        except ImportError:
            return True
        except Exception:
            return False

    def _to_iso8601(self, ts: float) -> str:
        if not ts:
            return ""
        t = time.localtime(ts)
        ms = int((ts - int(ts)) * 1000)
        return time.strftime('%Y-%m-%dT%H:%M:%S', t) + f'.{ms:03d}Z'

    @staticmethod
    def _compute_hash(values: list) -> str:
        try:
            data_str = json.dumps(values, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(data_str.encode()).hexdigest()[:16]
        except Exception:
            return ""

    def _build_metadata(self, result: Any = None) -> dict:
        ts = result.timestamp if result and hasattr(result, 'timestamp') else time.time()
        return {
            'device_id': result.device_id if result and hasattr(result, 'device_id') else self._device_id,
            'timestamp': self._to_iso8601(ts),
            'timestamp_ms': int(ts * 1000),
            'data_version': self._data_version,
            'gateway_id': self._gateway_id,
            'gateway_status': 'running',
            'sequence': int(time.time() * 1000) % 1000000,
        }


json_formatter = JsonFormatter()