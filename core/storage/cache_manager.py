import time
import threading
from typing import List, Dict, Any, Optional, Callable

from config.config_manager import CacheConfig
from core.storage.database import db
from utils.logger import log_manager


class CacheManager:
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
        self._configs: Dict[str, CacheConfig] = {}
        self._upload_callbacks: Dict[str, Callable[[List[Dict]], bool]] = {}
        self._upload_thread: Optional[threading.Thread] = None
        self._running = False

    def register_device(self, device_id: str, config: CacheConfig,
                        upload_callback: Callable[[List[Dict]], bool]):
        self._configs[device_id] = config
        self._upload_callbacks[device_id] = upload_callback

    def unregister_device(self, device_id: str):
        self._configs.pop(device_id, None)
        self._upload_callbacks.pop(device_id, None)

    def cache_data(self, device_id: str, topic: str, payload: str, qos: int = 1):
        cfg = self._configs.get(device_id)
        if not cfg:
            return
        self._enforce_cache_limit(device_id, cfg)
        conn = db._get_conn()
        conn.execute(
            """INSERT INTO upload_cache (device_id, topic, payload, qos, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (device_id, topic, payload, qos, time.time())
        )
        conn.commit()

    def _enforce_cache_limit(self, device_id: str, config: CacheConfig):
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM upload_cache WHERE device_id = ?",
            (device_id,)
        )
        count = cursor.fetchone()['cnt']
        if count >= config.max_records:
            if config.full_strategy == 'overwrite_oldest':
                excess = count - config.max_records + 1
                conn.execute(
                    """DELETE FROM upload_cache WHERE id IN
                       (SELECT id FROM upload_cache WHERE device_id = ?
                        ORDER BY timestamp ASC LIMIT ?)""",
                    (device_id, excess)
                )
                conn.commit()
            elif config.full_strategy == 'stop_collect':
                log_manager.warn(f"缓存[{device_id}]", "缓存已满，停止缓存")
        if config.max_hours > 0:
            cutoff = time.time() - config.max_hours * 3600
            conn.execute(
                "DELETE FROM upload_cache WHERE device_id = ? AND timestamp < ?",
                (device_id, cutoff)
            )
            conn.commit()

    def start_upload_worker(self, check_interval: float = 5.0):
        if self._running:
            return
        self._running = True
        self._upload_thread = threading.Thread(target=self._upload_loop, daemon=True,
                                               args=(check_interval,), name="CacheUploadWorker")
        self._upload_thread.start()
        log_manager.info("缓存管理", "缓存上传工作线程已启动")

    def stop_upload_worker(self):
        self._running = False

    def _upload_loop(self, check_interval: float):
        while self._running:
            try:
                self._process_cached_data()
            except Exception as e:
                log_manager.error("缓存管理", f"上传循环异常: {e}")
            time.sleep(check_interval)

    def _process_cached_data(self):
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT DISTINCT device_id FROM upload_cache WHERE uploaded = 0 ORDER BY timestamp ASC"
        )
        device_ids = [row['device_id'] for row in cursor.fetchall()]
        for device_id in device_ids:
            callback = self._upload_callbacks.get(device_id)
            if not callback:
                continue
            cursor = conn.execute(
                """SELECT * FROM upload_cache WHERE device_id = ? AND uploaded = 0
                   ORDER BY timestamp ASC LIMIT 100""",
                (device_id,)
            )
            records = [dict(row) for row in cursor.fetchall()]
            if not records:
                continue
            try:
                success = callback(records)
                if success:
                    ids = [r['id'] for r in records]
                    placeholders = ','.join(['?'] * len(ids))
                    conn.execute(
                        f"UPDATE upload_cache SET uploaded = 1 WHERE id IN ({placeholders})",
                        ids
                    )
                    conn.commit()
                    log_manager.info(f"缓存[{device_id}]", f"已补传 {len(records)} 条缓存数据")
                else:
                    conn.execute(
                        """UPDATE upload_cache SET retry_count = retry_count + 1
                           WHERE device_id = ? AND uploaded = 0""",
                        (device_id,)
                    )
                    conn.commit()
            except Exception as e:
                log_manager.error(f"缓存[{device_id}]", f"补传失败: {e}")

    def get_cache_status(self, device_id: str) -> Dict[str, Any]:
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN uploaded = 0 THEN 1 ELSE 0 END) as pending FROM upload_cache WHERE device_id = ?",
            (device_id,)
        )
        row = cursor.fetchone()
        if row:
            return {'total': row['total'] or 0, 'pending': row['pending'] or 0}
        return {'total': 0, 'pending': 0}

    def clear_cache(self, device_id: Optional[str] = None):
        conn = db._get_conn()
        if device_id:
            conn.execute("DELETE FROM upload_cache WHERE device_id = ?", (device_id,))
        else:
            conn.execute("DELETE FROM upload_cache")
        conn.commit()
        log_manager.info("缓存管理", f"已清除设备[{device_id}]的缓存数据" if device_id else "已清除所有缓存数据")

    def get_all_cache_status(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT device_id, COUNT(*) as total, SUM(CASE WHEN uploaded = 0 THEN 1 ELSE 0 END) as pending FROM upload_cache GROUP BY device_id"
        )
        for row in cursor.fetchall():
            result[row['device_id']] = {'total': row['total'] or 0, 'pending': row['pending'] or 0}
        return result


cache_manager = CacheManager()