import threading
import time
from typing import Any, Callable, Dict, List, Optional

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
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()

    def register_device(self, device_id: str, config: Optional[CacheConfig],
                        upload_callback: Callable[[List[Dict]], bool]):
        with self._state_lock:
            self._configs[device_id] = config or CacheConfig()
            self._upload_callbacks[device_id] = upload_callback

    def unregister_device(self, device_id: str):
        with self._state_lock:
            self._configs.pop(device_id, None)
            self._upload_callbacks.pop(device_id, None)

    def cache_data(self, device_id: str, topic: str, payload: str, qos: int = 1) -> bool:
        with self._state_lock:
            config = self._configs.get(device_id)
        if config is None:
            log_manager.warn(f"缓存[{device_id}]", "设备未注册缓存配置，数据未入队")
            return False

        conn = db._get_conn()
        with db._lock:
            self._delete_expired(conn, device_id, config)
            if not self._enforce_cache_limit(conn, device_id, config):
                conn.commit()
                return False
            conn.execute(
                """INSERT INTO upload_cache
                   (device_id, topic, payload, qos, timestamp, next_retry_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (device_id, topic, payload, qos, time.time(), 0),
            )
            conn.commit()
        return True

    @staticmethod
    def _delete_expired(conn, device_id: str, config: CacheConfig):
        if config.max_hours <= 0:
            return
        cutoff = time.time() - config.max_hours * 3600
        conn.execute(
            "DELETE FROM upload_cache WHERE device_id = ? AND timestamp < ?",
            (device_id, cutoff),
        )

    @staticmethod
    def _enforce_cache_limit(conn, device_id: str, config: CacheConfig) -> bool:
        conn.execute(
            "DELETE FROM upload_cache WHERE device_id = ? AND uploaded = 1",
            (device_id,),
        )
        count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM upload_cache WHERE device_id = ?",
            (device_id,),
        ).fetchone()['cnt']
        if count < config.max_records:
            return True
        if config.full_strategy == 'overwrite_oldest':
            excess = count - config.max_records + 1
            conn.execute(
                """DELETE FROM upload_cache WHERE id IN
                   (SELECT id FROM upload_cache WHERE device_id = ?
                    ORDER BY timestamp ASC, id ASC LIMIT ?)""",
                (device_id, excess),
            )
            return True
        log_manager.warn(f"缓存[{device_id}]", "缓存已满，拒绝新增缓存数据")
        return False

    def start_upload_worker(self, check_interval: float = 5.0):
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._upload_thread = threading.Thread(
                target=self._upload_loop,
                daemon=True,
                args=(check_interval,),
                name="CacheUploadWorker",
            )
            self._upload_thread.start()
        log_manager.info("缓存管理", "缓存上传工作线程已启动")

    def stop_upload_worker(self, timeout: float = 5.0):
        with self._state_lock:
            self._running = False
            self._stop_event.set()
            thread = self._upload_thread
            self._upload_thread = None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _upload_loop(self, check_interval: float):
        while not self._stop_event.is_set():
            try:
                self._process_cached_data()
            except Exception as exc:
                log_manager.error("缓存管理", f"上传循环异常: {exc}")
            self._stop_event.wait(check_interval)

    def _process_cached_data(self):
        conn = db._get_conn()
        with self._state_lock:
            configs = dict(self._configs)
        for device_id, config in configs.items():
            with db._lock:
                self._delete_expired(conn, device_id, config)
                conn.commit()
        now = time.time()
        device_ids = [
            row['device_id'] for row in conn.execute(
                """SELECT DISTINCT device_id FROM upload_cache
                   WHERE uploaded = 0 AND dead_letter = 0 AND next_retry_at <= ?
                   ORDER BY timestamp ASC""",
                (now,),
            ).fetchall()
        ]
        for device_id in device_ids:
            with self._state_lock:
                callback = self._upload_callbacks.get(device_id)
                config = self._configs.get(device_id, CacheConfig())
            if not callback:
                continue
            records = [
                dict(row) for row in conn.execute(
                    """SELECT * FROM upload_cache
                       WHERE device_id = ? AND uploaded = 0 AND dead_letter = 0
                         AND next_retry_at <= ?
                       ORDER BY timestamp ASC, id ASC LIMIT 100""",
                    (device_id, time.time()),
                ).fetchall()
            ]
            if not records:
                continue
            error = "上传回调返回失败"
            try:
                success = bool(callback(records))
            except Exception as exc:
                success = False
                error = str(exc)
            if success:
                ids = [record['id'] for record in records]
                placeholders = ','.join('?' for _ in ids)
                with db._lock:
                    conn.execute(
                        f"DELETE FROM upload_cache WHERE uploaded = 0 AND id IN ({placeholders})",
                        ids,
                    )
                    conn.commit()
                log_manager.info(f"缓存[{device_id}]", f"已补传 {len(records)} 条缓存数据")
            else:
                self._record_failure(conn, records, config, error)

    @staticmethod
    def _record_failure(conn, records: List[Dict], config: CacheConfig, error: str):
        max_retries = max(1, int(config.max_retries))
        base_delay = max(0.1, float(config.retry_backoff_seconds))
        max_delay = max(base_delay, float(config.max_backoff_seconds))
        now = time.time()
        updates = []
        for record in records:
            retry_count = int(record.get('retry_count', 0)) + 1
            delay = min(max_delay, base_delay * (2 ** min(retry_count - 1, 12)))
            updates.append((
                retry_count,
                now + delay,
                error[:500],
                1 if retry_count >= max_retries else 0,
                record['id'],
            ))
        with db._lock:
            conn.executemany(
                """UPDATE upload_cache
                   SET retry_count = ?, next_retry_at = ?, last_error = ?, dead_letter = ?
                   WHERE id = ? AND uploaded = 0""",
                updates,
            )
            conn.commit()

    def get_cache_status(self, device_id: str) -> Dict[str, Any]:
        conn = db._get_conn()
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN uploaded = 0 AND dead_letter = 0 THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN dead_letter = 1 THEN 1 ELSE 0 END) AS dead_letter
               FROM upload_cache WHERE device_id = ?""",
            (device_id,),
        ).fetchone()
        return {
            'total': row['total'] or 0,
            'pending': row['pending'] or 0,
            'dead_letter': row['dead_letter'] or 0,
        }

    def clear_cache(self, device_id: Optional[str] = None):
        conn = db._get_conn()
        if device_id:
            conn.execute("DELETE FROM upload_cache WHERE device_id = ?", (device_id,))
        else:
            conn.execute("DELETE FROM upload_cache")
        conn.commit()
        log_manager.info("缓存管理", "已清除缓存数据")

    def get_all_cache_status(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        conn = db._get_conn()
        cursor = conn.execute(
            """SELECT device_id, COUNT(*) AS total,
                      SUM(CASE WHEN uploaded = 0 AND dead_letter = 0 THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN dead_letter = 1 THEN 1 ELSE 0 END) AS dead_letter
               FROM upload_cache GROUP BY device_id"""
        )
        for row in cursor.fetchall():
            result[row['device_id']] = {
                'total': row['total'] or 0,
                'pending': row['pending'] or 0,
                'dead_letter': row['dead_letter'] or 0,
            }
        return result


cache_manager = CacheManager()
