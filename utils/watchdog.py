import os
import sys
import time
import threading
import subprocess
from typing import Callable, Optional

from utils.logger import log_manager


class Watchdog:
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
        self._enabled = False
        self._check_interval = 5.0
        self._heartbeat_timeout = 30.0
        self._last_heartbeat = time.time()
        self._check_thread: Optional[threading.Thread] = None
        self._running = False
        self._restart_callback: Optional[Callable[[], None]] = None
        self._is_watchdog_process = False

    def enable(self, check_interval: float = 5.0, heartbeat_timeout: float = 30.0):
        self._enabled = True
        self._check_interval = check_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._last_heartbeat = time.time()
        if not self._running:
            self._running = True
            self._check_thread = threading.Thread(target=self._check_loop, daemon=True, name="WatchdogThread")
            self._check_thread.start()
        log_manager.info("系统", "看门狗已启用")

    def disable(self):
        self._enabled = False
        self._running = False
        log_manager.info("系统", "看门狗已禁用")

    def feed(self):
        self._last_heartbeat = time.time()

    def set_restart_callback(self, callback: Callable[[], None]):
        self._restart_callback = callback

    def restart_application(self):
        log_manager.warn("系统", "看门狗检测到异常，正在重启应用...")
        try:
            if self._restart_callback:
                self._restart_callback()
            python = sys.executable
            script = sys.argv[0]
            subprocess.Popen([python, script], creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0)
        except Exception as e:
            log_manager.error("系统", f"应用重启失败: {e}")
        finally:
            os._exit(0)

    def _check_loop(self):
        while self._running:
            try:
                if self._enabled:
                    elapsed = time.time() - self._last_heartbeat
                    if elapsed > self._heartbeat_timeout:
                        log_manager.error("系统", f"心跳超时 {elapsed:.1f}秒，准备重启")
                        self.restart_application()
                time.sleep(self._check_interval)
            except Exception as e:
                log_manager.error("系统", f"看门狗检查异常: {e}")
                time.sleep(self._check_interval)

    def get_status(self) -> dict:
        return {
            'enabled': self._enabled,
            'last_heartbeat': self._last_heartbeat,
            'heartbeat_timeout': self._heartbeat_timeout,
            'elapsed': time.time() - self._last_heartbeat
        }


watchdog = Watchdog()