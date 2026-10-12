import threading
from typing import Optional

from config.config_manager import AppConfig
from core.api.server import GatewayApiServer
from core.storage.cache_manager import cache_manager
from core.storage.database import db
from device.device_manager import device_manager
from utils.logger import log_manager


class GatewayRuntime:
    """Own the lifecycle of gateway background services.

    The UI is a delivery mechanism. This class owns services that must also be
    usable by a future headless/Windows-service entry point, keeping startup
    and shutdown ordering in one place.
    """

    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.api_server: Optional[GatewayApiServer] = None
        self._started = False
        self._stopped = False
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._started and not self._stopped

    def start(self) -> bool:
        with self._lock:
            if self._started and not self._stopped:
                return True
            self._started = True
            self._stopped = False

        try:
            db.start_maintenance(self.app_config.data_retention_days)
            self._start_api()
            log_manager.info("系统", "网关后台运行时已启动")
            return True
        except Exception:
            self.stop()
            raise

    def start_collection(self):
        if not self.is_running:
            raise RuntimeError("GatewayRuntime must be started before collection")
        if self.app_config.auto_start_collect:
            device_manager.start_all()
            log_manager.info("系统", "已按配置自动启动设备采集")

    def stop(self):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            api_server = self.api_server
            self.api_server = None

        errors = []
        for action in (
            lambda: api_server.stop() if api_server else None,
            device_manager.stop_all,
            cache_manager.stop_upload_worker,
            db.stop_maintenance,
        ):
            try:
                action()
            except Exception as exc:
                errors.append(exc)

        if errors:
            log_manager.error("系统", f"后台运行时清理存在 {len(errors)} 个异常")
            raise RuntimeError("gateway runtime shutdown failed") from errors[0]
        log_manager.info("系统", "网关后台运行时已停止")

    def _start_api(self):
        api_config = self.app_config.api
        if not api_config.enabled:
            return
        try:
            server = GatewayApiServer(
                host=api_config.host,
                port=api_config.port,
                device_status_provider=device_manager.get_all_device_status,
                cache_status_provider=cache_manager.get_all_cache_status,
            )
            server.start()
            self.api_server = server
            log_manager.info("系统", f"管理 API 已启动: {server.url}")
        except (OSError, ValueError) as exc:
            # The desktop UI remains useful when a configured port is busy or
            # a remote bind is missing its token.
            log_manager.warn("系统", f"管理 API 启动失败，桌面模式继续运行: {exc}")
