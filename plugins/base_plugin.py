from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BasePlugin(ABC):
    PLUGIN_NAME = "base"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "基础插件"
    PLUGIN_AUTHOR = ""

    def __init__(self):
        self._initialized = False
        self._enabled = True

    @property
    def name(self) -> str:
        return self.PLUGIN_NAME

    @property
    def version(self) -> str:
        return self.PLUGIN_VERSION

    @property
    def description(self) -> str:
        return self.PLUGIN_DESCRIPTION

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def initialize(self) -> bool:
        if self._initialized:
            return True
        self._initialized = True
        return self.on_initialize()

    def shutdown(self):
        if self._initialized:
            self.on_shutdown()
            self._initialized = False

    @abstractmethod
    def on_initialize(self) -> bool:
        pass

    @abstractmethod
    def on_shutdown(self):
        pass

    def on_data_received(self, device_id: str, data: Dict[str, Any]):
        pass

    def on_device_status_changed(self, device_id: str, status: str):
        pass

    def on_mqtt_message(self, topic: str, payload: str):
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        return {}

    def get_config(self) -> Dict[str, Any]:
        return {}

    def set_config(self, config: Dict[str, Any]):
        pass


class PluginManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._plugins: Dict[str, BasePlugin] = {}

    def register_plugin(self, plugin: BasePlugin) -> bool:
        if plugin.name in self._plugins:
            return False
        self._plugins[plugin.name] = plugin
        plugin.initialize()
        return True

    def unregister_plugin(self, name: str) -> bool:
        plugin = self._plugins.pop(name, None)
        if plugin:
            plugin.shutdown()
            return True
        return False

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def get_all_plugins(self) -> List[BasePlugin]:
        return list(self._plugins.values())

    def notify_data_received(self, device_id: str, data: Dict[str, Any]):
        for plugin in self._plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_data_received(device_id, data)
                except Exception:
                    pass

    def notify_device_status(self, device_id: str, status: str):
        for plugin in self._plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_device_status_changed(device_id, status)
                except Exception:
                    pass

    def notify_mqtt_message(self, topic: str, payload: str):
        for plugin in self._plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_mqtt_message(topic, payload)
                except Exception:
                    pass

    def shutdown_all(self):
        for plugin in self._plugins.values():
            try:
                plugin.shutdown()
            except Exception:
                pass
        self._plugins.clear()


plugin_manager = PluginManager()