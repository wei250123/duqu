import time
import copy
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from core.data_types import CollectResult
from core.processor.data_filter import DataFilter
from core.processor.data_aggregator import DataAggregator
from core.processor.data_transformer import DataTransformer, AlarmChecker
from core.processor.moving_filter import FilterBank
from core.processor.converter import DataConverter
from core.processor.computation import DataComputation
from core.processor.fusion import SensorFusion, sensor_fusion
from core.processor.lua_executor import lua_executor
from core.processor.json_formatter import json_formatter
from core.processor.event_trigger import EventManager, TriggerRule, event_manager
from config.config_manager import (DeviceConfig, DataFilterConfig, DataAggregateConfig,
                                    PipelineConfig, PipelineRule, PipelineStage)
from utils.logger import log_manager

filter_bank = FilterBank(window_size=10, filter_type="sma", alpha=0.3)


class Pipeline:
    def __init__(self, device_config: DeviceConfig):
        self._device_config = device_config
        self._pipeline_config = device_config.pipeline
        self._filter = DataFilter(device_config.data_filter)
        self._aggregator = DataAggregator(device_config.data_aggregate)
        self._transformer = DataTransformer(
            device_id=device_config.device_id,
            topic_prefix=device_config.mqtt.topic_prefix
        )
        self._alarm_checker = AlarmChecker()
        self._json_formatter = json_formatter
        self._lua_context: Dict[str, Any] = {}
        self._fusion_buffers: Dict[str, List[CollectResult]] = {}
        self._event_manager = event_manager
        self._init_lua_context()
        self._sequence = 0

    @property
    def pipeline_config(self) -> PipelineConfig:
        return self._pipeline_config

    @pipeline_config.setter
    def pipeline_config(self, value: PipelineConfig):
        self._pipeline_config = value

    def process(self, result: CollectResult) -> Optional[CollectResult]:
        if not self._pipeline_config.enabled:
            return self._process_default(result)
        current = result
        for rule in self._pipeline_config.rules:
            if not rule.enabled:
                continue
            if rule.should_skip(current):
                continue
            output = self._execute_rule(rule, current)
            if output is None and rule.on_fail == 'abort':
                return None
            if output is not None:
                current = output
            if rule.loop and rule.loop_max > 0:
                loop_count = 0
                while loop_count < rule.loop_max:
                    loop_count += 1
                    loop_output = self._execute_rule(rule, current)
                    if loop_output is None:
                        break
                    current = loop_output
        self._sequence += 1
        return current

    def process_batch(self, results: List[CollectResult]) -> List[CollectResult]:
        processed = []
        for r in results:
            pr = self.process(r)
            if pr is not None:
                processed.append(pr)
        if self._pipeline_config.batch_operations:
            processed = self._apply_batch_operations(processed)
        return processed

    def output_json(self, result: CollectResult,
                    custom_template: Optional[dict] = None) -> str:
        if custom_template:
            data = self._json_formatter.format_single(result, custom_template)
        elif self._pipeline_config.json_template:
            data = self._json_formatter.format_single(
                result, self._pipeline_config.json_template)
        else:
            data = self._json_formatter.format_single(result)
        if self._pipeline_config.json_schema:
            validated = self._json_formatter.validate_schema(data)
            if not validated:
                log_manager.warn("流水线", "JSON Schema验证失败")
                data['_schema_valid'] = False
        return self._json_formatter.to_json(data)

    def output_json_batch(self, results: List[CollectResult]) -> str:
        template = self._pipeline_config.json_template or None
        data = self._json_formatter.format_batch(
            results, template,
            batch_size=self._pipeline_config.batch_size
        )
        return self._json_formatter.to_json(data)

    def _process_default(self, result: CollectResult) -> Optional[CollectResult]:
        current = result
        scaled = self._apply_scale_offset(current)
        if scaled:
            current = scaled
        if current.value is not None:
            filtered_val = filter_bank.feed(
                f"{current.device_id}:{current.point_name}", current.value)
            if filtered_val is not None:
                current.filtered_value = filtered_val
        if self._filter.should_upload(current):
            aggregated = self._aggregator.feed(current)
            if aggregated:
                current = aggregated
        alarm = self._alarm_checker.check(current)
        if alarm:
            current.is_alarm = True
        self._event_manager.process_result(current)
        return current

    def _execute_rule(self, rule: PipelineRule,
                      result: CollectResult) -> Optional[CollectResult]:
        try:
            if rule.stage == PipelineStage.CONVERT:
                return self._handle_convert(rule, result)
            elif rule.stage == PipelineStage.COMPUTE:
                return self._handle_compute(rule, result)
            elif rule.stage == PipelineStage.FILTER:
                return self._handle_filter(rule, result)
            elif rule.stage == PipelineStage.AGGREGATE:
                return self._handle_aggregate(rule, result)
            elif rule.stage == PipelineStage.FUSION:
                return self._handle_fusion(rule, result)
            elif rule.stage == PipelineStage.LUA:
                return self._handle_lua(rule, result)
            elif rule.stage == PipelineStage.TRANSFORM:
                return self._handle_transform(rule, result)
            elif rule.stage == PipelineStage.ENCRYPT:
                return self._handle_encrypt(rule, result)
            elif rule.stage == PipelineStage.CUSTOM:
                return self._handle_custom(rule, result)
            return result
        except Exception as e:
            log_manager.error("流水线", f"规则[{rule.name}]执行异常: {e}")
            return result if rule.on_fail != 'abort' else None

    def _handle_convert(self, rule: PipelineRule,
                        result: CollectResult) -> Optional[CollectResult]:
        r = copy.copy(result)
        conv_type = rule.params.get('type', 'linear')
        conv_params = rule.params.get('type_params', {})
        if conv_type == 'linear':
            new_value = DataConverter.convert(r.value, DataConverter.LINEAR,
                                              {'k': conv_params.get('k', 1.0),
                                               'b': conv_params.get('b', 0.0)})
        elif conv_type == 'scale_offset':
            new_value = DataConverter.convert(r.value, DataConverter.SCALE_OFFSET,
                                              {'scale': conv_params.get('scale', 1.0),
                                               'offset': conv_params.get('offset', 0.0)})
        elif conv_type == 'bit_extract':
            new_value = DataConverter.convert(r.value, DataConverter.BIT_EXTRACT, conv_params)
        elif conv_type == 'round':
            new_value = DataConverter.convert(r.value, DataConverter.ROUND,
                                              {'decimals': conv_params.get('decimals', 2)})
        elif conv_type == 'clamp':
            new_value = DataConverter.convert(r.value, DataConverter.CLAMP, conv_params)
        elif conv_type == 'enum_map':
            new_value = DataConverter.convert(r.value, DataConverter.ENUM_MAP, conv_params)
        elif conv_type == 'to_boolean':
            new_value = DataConverter.convert(r.value, DataConverter.TO_BOOLEAN)
        elif conv_type == 'to_integer':
            new_value = DataConverter.convert(r.value, DataConverter.TO_INTEGER)
        elif conv_type == 'to_float':
            new_value = DataConverter.convert(r.value, DataConverter.TO_FLOAT)
        elif conv_type == 'number_to_string':
            new_value = DataConverter.convert(r.value, DataConverter.NUMBER_TO_STRING, conv_params)
        elif conv_type == 'string_to_number':
            new_value = DataConverter.convert(r.value, DataConverter.STRING_TO_NUMBER, conv_params)
        else:
            new_value = r.value
        r.raw_value = r.value
        r.value = new_value
        if rule.params.get('set_unit'):
            r.unit = rule.params['set_unit']
        return r

    def _handle_compute(self, rule: PipelineRule,
                        result: CollectResult) -> Optional[CollectResult]:
        r = copy.copy(result)
        op = rule.params.get('operation', 'linear_formula')
        op_params = rule.params.get('operation_params', {})
        if op == 'linear_formula':
            new_value = DataComputation.compute(r.value, DataComputation.LINEAR_FORMULA, op_params)
        elif op == 'expression':
            new_value = DataComputation.compute(r.value, DataComputation.EXPRESSION,
                                                {'expr': op_params.get('expr', 'x')})
        elif op == 'unit_convert':
            from_unit = op_params.get('from_unit', r.unit)
            to_unit = op_params.get('to_unit', r.unit)
            factor = DataComputation.get_unit_factor(from_unit, to_unit)
            if factor is not None:
                new_value = float(r.value) * factor if r.value is not None else None
            else:
                new_value = DataComputation.convert_unit(float(r.value), from_unit, to_unit)
            if rule.params.get('set_unit'):
                r.unit = to_unit
        else:
            new_value = DataComputation.compute(r.value, op, op_params)
        if new_value is not None:
            r.raw_value = r.value
            r.value = new_value
        return r

    def _handle_filter(self, rule: PipelineRule,
                       result: CollectResult) -> Optional[CollectResult]:
        filter_type = rule.params.get('type', 'threshold')
        filter_params = rule.params.get('filter_params', {})

        if filter_type == 'null':
            if result.value is None:
                return None
        elif filter_type == 'threshold':
            lo = filter_params.get('min')
            hi = filter_params.get('max')
            if result.value is not None:
                v = float(result.value)
                if lo is not None and v < lo:
                    return None
                if hi is not None and v > hi:
                    return None
        elif filter_type == 'outlier':
            lo = filter_params.get('min')
            hi = filter_params.get('max')
            if result.value is not None:
                v = float(result.value)
                if lo is not None and v < lo:
                    return None
                if hi is not None and v > hi:
                    return None
        elif filter_type == 'duplicate':
            key = result.point_name
            last_val = self._lua_context.get('_filter_last_' + key)
            if last_val == result.value:
                return None
            self._lua_context['_filter_last_' + key] = result.value
        elif filter_type == 'change':
            key = result.point_name
            last_val = self._lua_context.get('_filter_last_' + key)
            if last_val is not None and last_val != 0:
                min_change = filter_params.get('min_change_percent', 0)
                change = abs((float(result.value) - float(last_val)) / float(last_val) * 100)
                if change < min_change:
                    return None
            self._lua_context['_filter_last_' + key] = result.value
        elif filter_type == 'conditional':
            expr = filter_params.get('expr', 'True')
            if result.value is not None:
                allowed = {'x': float(result.value), 'True': True, 'False': False}
                if not eval(expr, {'__builtins__': {}}, allowed):
                    return None
        return result

    def _handle_aggregate(self, rule: PipelineRule,
                          result: CollectResult) -> Optional[CollectResult]:
        agg_type = rule.params.get('type', 'sliding_window')
        agg_params = rule.params.get('agg_params', {})
        window_size = agg_params.get('window_size', 10)
        key = result.point_name
        if key not in self._fusion_buffers:
            self._fusion_buffers[key] = []
        buffer = self._fusion_buffers[key]
        buffer.append(result)
        if len(buffer) > window_size:
            buffer.pop(0)
        if len(buffer) < window_size or rule.params.get('wait_full', True):
            return result
        method = agg_params.get('method', 'avg')
        values = [float(r.value) for r in buffer if r.value is not None]
        if not values:
            return result
        if method == 'avg':
            agg_value = sum(values) / len(values)
        elif method == 'max':
            agg_value = max(values)
        elif method == 'min':
            agg_value = min(values)
        elif method == 'sum':
            agg_value = sum(values)
        elif method == 'cumulative':
            cumulative_key = '_cumul_' + key
            last_cumul = self._lua_context.get(cumulative_key, 0.0)
            agg_value = last_cumul + float(result.value) if result.value else last_cumul
            self._lua_context[cumulative_key] = agg_value
        elif method == 'median':
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            agg_value = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        elif method == 'last':
            agg_value = values[-1]
        else:
            agg_value = values[-1]
        r = copy.copy(buffer[-1])
        r.raw_value = r.value
        r.value = agg_value
        return r

    def _handle_fusion(self, rule: PipelineRule,
                       result: CollectResult) -> Optional[CollectResult]:
        fusion_type = rule.params.get('type', 'weighted_avg')
        fusion_params = rule.params.get('fusion_params', {})
        buffer_key = rule.params.get('buffer_key', result.point_name)
        if buffer_key not in self._fusion_buffers:
            self._fusion_buffers[buffer_key] = []
        buffer = self._fusion_buffers[buffer_key]
        buffer.append(result)
        max_buf = fusion_params.get('buffer_size', 5)
        if len(buffer) > max_buf:
            buffer.pop(0)
        min_required = fusion_params.get('min_sensors', 2)
        if len(buffer) < min_required:
            return result
        fused = sensor_fusion.fuse(
            list(buffer),
            fusion_type,
            {
                'weights': fusion_params.get('weights'),
                'output_name': result.point_name,
                'process_noise': fusion_params.get('process_noise', 0.01),
                'measurement_noise': fusion_params.get('measurement_noise', 0.1),
                'alpha': fusion_params.get('alpha', 0.98),
            }
        )
        if fused:
            buffer.clear()
            return fused
        return result

    def _handle_lua(self, rule: PipelineRule,
                    result: CollectResult) -> Optional[CollectResult]:
        if not lua_executor.available:
            return result
        script_template = rule.params.get('script', '')
        script = script_template.format(
            device_id=result.device_id,
            point_name=result.point_name,
            value=result.value,
            raw_value=result.raw_value,
            unit=result.unit,
            timestamp=result.timestamp,
        )
        context = {
            'value': result.value,
            'raw_value': result.raw_value,
            'unit': result.unit,
            'point_name': result.point_name,
        }
        context.update(self._lua_context)
        out = lua_executor.execute(script, context)
        if isinstance(out, dict):
            r = copy.copy(result)
            r.value = out.get('value', result.value)
            r.unit = out.get('unit', result.unit)
            for k, v in out.items():
                self._lua_context[k] = v
            return r
        elif out is not None:
            r = copy.copy(result)
            r.raw_value = r.value
            r.value = out
            return r
        return result

    def _handle_transform(self, rule: PipelineRule,
                          result: CollectResult) -> Optional[CollectResult]:
        return result

    def _handle_encrypt(self, rule: PipelineRule,
                        result: CollectResult) -> Optional[CollectResult]:
        if result.value is not None:
            try:
                from core.security.encryption import data_encryptor
                r = copy.copy(result)
                r.raw_value = result.value
                r.value = data_encryptor.encrypt(str(result.value))
                return r
            except Exception as e:
                log_manager.error("流水线", f"加密失败: {e}")
        return result

    def _handle_custom(self, rule: PipelineRule,
                       result: CollectResult) -> Optional[CollectResult]:
        handler = rule.params.get('handler')
        if handler and callable(handler):
            return handler(result)
        return result

    def _apply_scale_offset(self, result: CollectResult) -> Optional[CollectResult]:
        for point in self._device_config.collect.points:
            if point.name == result.point_name:
                if point.scale != 1.0 or point.offset != 0.0:
                    r = copy.copy(result)
                    if r.value is not None:
                        r.raw_value = r.value
                        r.value = float(r.value) * point.scale + point.offset
                    return r
        return result

    def _apply_batch_operations(self,
                                results: List[CollectResult]) -> List[CollectResult]:
        for op in self._pipeline_config.batch_operations:
            if op.get('type') == 'sort':
                key = op.get('by', 'point_name')
                reverse = op.get('reverse', False)
                results.sort(key=lambda r: getattr(r, key, ''), reverse=reverse)
            elif op.get('type') == 'limit':
                limit = op.get('count', 100)
                results = results[:limit]
            elif op.get('type') == 'dedup':
                seen = set()
                unique = []
                for r in results:
                    if r.point_name not in seen:
                        seen.add(r.point_name)
                        unique.append(r)
                results = unique
        return results

    def _init_lua_context(self):
        self._lua_context = {
            'pi': 3.141592653589793,
            'e': 2.718281828459045,
        }

    def reset(self):
        self._filter.reset()
        self._aggregator.reset()
        self._alarm_checker.clear_history()
        self._fusion_buffers.clear()
        self._lua_context = {}
        self._init_lua_context()
        self._sequence = 0
        sensor_fusion.reset()

    def get_pipeline_info(self) -> dict:
        return {
            'enabled': self._pipeline_config.enabled,
            'rules_count': len(self._pipeline_config.rules),
            'batch_size': self._pipeline_config.batch_size,
            'json_schema': self._pipeline_config.json_schema is not None,
            'lua_available': lua_executor.available,
        }