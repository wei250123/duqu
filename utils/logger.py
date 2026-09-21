import os
import sys
import logging
import logging.handlers
from datetime import datetime
from typing import Optional, Dict, Callable, List
from enum import IntEnum

from config.config_manager import config_manager, LOG_DIR


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARN = logging.WARN
    ERROR = logging.ERROR
    FATAL = logging.CRITICAL


class LogEntry:
    def __init__(self, level: str, module: str, message: str, timestamp: Optional[datetime] = None):
        self.timestamp = timestamp or datetime.now()
        self.level = level
        self.module = module
        self.message = message

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [{self.level}] [{self.module}] {self.message}"

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'level': self.level,
            'module': self.module,
            'message': self.message
        }


class LogManager:
    _instance = None
    MAX_BUFFER_SIZE = 10000

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._logger = logging.getLogger("IIoTGateway")
        self._logger.setLevel(logging.DEBUG)
        self._handlers: Dict[str, logging.Handler] = {}
        self._log_buffer: List[LogEntry] = []
        self._callbacks: List[Callable[[LogEntry], None]] = []
        self._paused = False
        self._filters: Dict[str, str] = {}
        self._level_map = {
            LogLevel.DEBUG: "DEBUG",
            LogLevel.INFO: "INFO",
            LogLevel.WARN: "WARN",
            LogLevel.ERROR: "ERROR",
            LogLevel.FATAL: "FATAL"
        }
        self._init_handlers()

    def _init_handlers(self):
        log_config = config_manager.app_config.log
        self._logger.handlers.clear()
        self._handlers.clear()
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(LOG_DIR, 'gateway.log')
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=log_config.max_file_size_mb * 1024 * 1024,
            backupCount=log_config.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)
        self._handlers['file'] = file_handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        self._handlers['console'] = console_handler
        self.set_level(LogLevel.INFO)

    def set_level(self, level: LogLevel):
        self._logger.setLevel(level.value)
        log_config = config_manager.app_config.log
        log_config.level = self._level_map.get(level, "INFO")
        config_manager.save_app_config()

    def get_level(self) -> LogLevel:
        current = self._logger.level
        for lvl in LogLevel:
            if lvl.value == current:
                return lvl
        return LogLevel.INFO

    def log(self, level: LogLevel, module: str, message: str):
        if self._paused:
            return

        
        if self._filters:
            if 'level' in self._filters and self._level_map.get(level, "") != self._filters['level']:
                return
            if 'module' in self._filters and module != self._filters['module']:
                return
            if 'keyword' in self._filters and self._filters['keyword'].lower() not in message.lower():
                return
            
        entry = LogEntry(self._level_map.get(level, "UNKNOWN"), module, message)
        self._log_buffer.append(entry)
        if len(self._log_buffer) > self.MAX_BUFFER_SIZE:
            self._log_buffer = self._log_buffer[-self.MAX_BUFFER_SIZE:]
        log_msg = f"[{module}] {message}"
        if level == LogLevel.DEBUG:
            self._logger.debug(log_msg)
        elif level == LogLevel.INFO:
            self._logger.info(log_msg)
        elif level == LogLevel.WARN:
            self._logger.warning(log_msg)
        elif level == LogLevel.ERROR:
            self._logger.error(log_msg)
        elif level == LogLevel.FATAL:
            self._logger.critical(log_msg)
        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def debug(self, module: str, message: str):
        self.log(LogLevel.DEBUG, module, message)

    def info(self, module: str, message: str):
        self.log(LogLevel.INFO, module, message)

    def warn(self, module: str, message: str):
        self.log(LogLevel.WARN, module, message)

    def error(self, module: str, message: str):
        self.log(LogLevel.ERROR, module, message)

    def fatal(self, module: str, message: str):
        self.log(LogLevel.FATAL, module, message)

    def add_callback(self, callback: Callable[[LogEntry], None]):
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[LogEntry], None]):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_logs(self, level: Optional[str] = None, module: Optional[str] = None,
                 keyword: Optional[str] = None, limit: int = 500) -> List[LogEntry]:
        result = self._log_buffer.copy()
        if level:
            result = [e for e in result if e.level == level.upper()]
        if module:
            result = [e for e in result if e.module == module]
        if keyword:
            result = [e for e in result if keyword.lower() in e.message.lower()]
        return result[-limit:]

    def clear_buffer(self):
        self._log_buffer.clear()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def set_filter(self, level: Optional[str] = None, module: Optional[str] = None,
                   keyword: Optional[str] = None):
        self._filters = {}
        if level:
            self._filters['level'] = level.upper()
        if module:
            self._filters['module'] = module
        if keyword:
            self._filters['keyword'] = keyword

    def clear_filter(self):
        self._filters = {}

    def get_modules(self) -> List[str]:
        modules = set()
        for entry in self._log_buffer:
            modules.add(entry.module)
        return sorted(modules)

    def search_logs(self, query: str, limit: int = 500) -> List[LogEntry]:
        query_lower = query.lower()
        return [e for e in self._log_buffer if query_lower in e.message.lower()][-limit:]


log_manager = LogManager()