from typing import Any, Dict, List, Optional
from utils.logger import log_manager


class LuaExecutor:
    def __init__(self):
        self._lua_available = False
        self._lua = None
        self._try_load_lua()

    def _try_load_lua(self):
        try:
            import lupa
            self._lua = lupa.LuaRuntime(unpack_returned_tuples=True)
            self._lua_available = True
            log_manager.info("Lua执行器", "Lupa库已加载，支持Lua脚本执行")
        except ImportError:
            log_manager.warn("Lua执行器", "Lupa库未安装，Lua脚本功能不可用。请运行: pip install lupa")

    @property
    def available(self) -> bool:
        return self._lua_available

    def execute(self, script: str, context: Optional[dict] = None) -> Any:
        if not self._lua_available:
            log_manager.error("Lua执行器", "Lua环境不可用")
            return None
        try:
            lua_globals = self._lua.globals()
            if context:
                for key, value in context.items():
                    lua_globals[key] = self._convert_to_lua(value)
            result = self._lua.execute(script)
            return self._convert_from_lua(result)
        except Exception as e:
            log_manager.error("Lua执行器", f"脚本执行失败: {e}")
            return None

    def execute_function(self, func_name: str, args: Optional[list] = None,
                         context: Optional[dict] = None) -> Any:
        if not self._lua_available:
            return None
        try:
            lua_globals = self._lua.globals()
            if context:
                for key, value in context.items():
                    lua_globals[key] = self._convert_to_lua(value)
            lua_func = getattr(lua_globals, func_name, None)
            if lua_func is None:
                log_manager.error("Lua执行器", f"函数 {func_name} 未定义")
                return None
            args = args or []
            lua_args = [self._convert_to_lua(a) for a in args]
            return self._convert_from_lua(lua_func(*lua_args))
        except Exception as e:
            log_manager.error("Lua执行器", f"函数执行失败: {e}")
            return None

    def load_script(self, script: str):
        if not self._lua_available:
            return
        try:
            self._lua.execute(script)
        except Exception as e:
            log_manager.error("Lua执行器", f"脚本加载失败: {e}")

    def set_global(self, name: str, value: Any):
        if not self._lua_available:
            return
        try:
            self._lua.globals()[name] = self._convert_to_lua(value)
        except Exception as e:
            log_manager.error("Lua执行器", f"设置全局变量失败: {e}")

    def get_global(self, name: str) -> Any:
        if not self._lua_available:
            return None
        try:
            return self._convert_from_lua(self._lua.globals()[name])
        except Exception:
            return None

    def _convert_to_lua(self, value: Any) -> Any:
        if isinstance(value, dict):
            tg = self._lua.table()
            for k, v in value.items():
                tg[k] = self._convert_to_lua(v)
            return tg
        elif isinstance(value, list):
            tg = self._lua.table()
            for i, v in enumerate(value):
                tg[i + 1] = self._convert_to_lua(v)
            return tg
        elif isinstance(value, bool):
            return value
        elif isinstance(value, (int, float, str)):
            return value
        elif value is None:
            return None
        return str(value)

    def _convert_from_lua(self, value: Any) -> Any:
        try:
            if value is None:
                return None
            if isinstance(value, (bool, int, float, str)):
                return value
            if self._lua_available and hasattr(value, 'values'):
                items = list(value.values())
                if not items:
                    return {}
                if isinstance(items[0], (list, tuple)) and hasattr(items[0], '__len__'):
                    keys = list(value.keys())
                    if keys and all(isinstance(k, (int, float)) for k in keys):
                        return [self._convert_from_lua(v) for v in items]
                result = {}
                for k in value.keys():
                    result[str(k)] = self._convert_from_lua(value[k])
                return result
            return str(value)
        except Exception:
            return str(value)


lua_executor = LuaExecutor()