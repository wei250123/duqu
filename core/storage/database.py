import os
import sqlite3
import threading
import json
import time
import csv
from typing import List, Dict, Any, Optional

from config.config_manager import DB_DIR
from utils.logger import log_manager


class Database:
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
        self._db_path = os.path.join(DB_DIR, 'gateway.db')
        self._local = threading.local()
        self._lock = threading.Lock()
        os.makedirs(DB_DIR, exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS data_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                point_name TEXT NOT NULL,
                value REAL,
                unit TEXT DEFAULT '',
                timestamp REAL NOT NULL,
                success INTEGER DEFAULT 1,
                is_alarm INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                raw_data TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_data_device_id ON data_records(device_id);
            CREATE INDEX IF NOT EXISTS idx_data_timestamp ON data_records(timestamp);
            CREATE INDEX IF NOT EXISTS idx_data_device_point ON data_records(device_id, point_name);
            
            CREATE TABLE IF NOT EXISTS alarm_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                point_name TEXT NOT NULL,
                value REAL,
                unit TEXT DEFAULT '',
                alarm_type TEXT NOT NULL,
                threshold REAL,
                timestamp REAL NOT NULL,
                description TEXT DEFAULT '',
                acknowledged INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );
            CREATE INDEX IF NOT EXISTS idx_alarm_device_id ON alarm_records(device_id);
            CREATE INDEX IF NOT EXISTS idx_alarm_timestamp ON alarm_records(timestamp);
            
            CREATE TABLE IF NOT EXISTS device_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT DEFAULT '',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_status_device ON device_status_log(device_id);
            
            CREATE TABLE IF NOT EXISTS upload_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                qos INTEGER DEFAULT 1,
                timestamp REAL NOT NULL,
                uploaded INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cache_device ON upload_cache(device_id);
            CREATE INDEX IF NOT EXISTS idx_cache_uploaded ON upload_cache(uploaded);
        """)
        conn.commit()

    def insert_data(self, device_id: str, point_name: str, value: Any, unit: str = "",
                    timestamp: Optional[float] = None, success: bool = True,
                    is_alarm: bool = False, raw_data: str = "") -> int:
        ts = timestamp or time.time()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO data_records (device_id, point_name, value, unit, timestamp, success, is_alarm, raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (device_id, point_name, value, unit, ts, 1 if success else 0,
             1 if is_alarm else 0, raw_data)
        )
        conn.commit()
        return cursor.lastrowid

    def insert_data_batch(self, records: List[Dict[str, Any]]):
        conn = self._get_conn()
        with self._lock:
            conn.executemany(
                """INSERT INTO data_records (device_id, point_name, value, unit, timestamp, success, is_alarm)
                   VALUES (:device_id, :point_name, :value, :unit, :timestamp, :success, :is_alarm)""",
                records
            )
            conn.commit()

    def insert_alarm(self, device_id: str, point_name: str, value: float, unit: str,
                     alarm_type: str, threshold: float, description: str = "",
                     timestamp: Optional[float] = None) -> int:
        ts = timestamp or time.time()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO alarm_records (device_id, point_name, value, unit, alarm_type, threshold, timestamp, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (device_id, point_name, value, unit, alarm_type, threshold, ts, description)
        )
        conn.commit()
        return cursor.lastrowid

    def query_data(self, device_id: Optional[str] = None, point_name: Optional[str] = None,
                   start_time: Optional[float] = None, end_time: Optional[float] = None,
                   limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        sql = "SELECT * FROM data_records WHERE 1=1"
        params = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        if point_name:
            sql += " AND point_name = ?"
            params.append(point_name)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def query_alarms(self, device_id: Optional[str] = None,
                     start_time: Optional[float] = None, end_time: Optional[float] = None,
                     acknowledged: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        sql = "SELECT * FROM alarm_records WHERE 1=1"
        params = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        if acknowledged is not None:
            sql += " AND acknowledged = ?"
            params.append(acknowledged)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def acknowledge_alarm(self, alarm_id: int):
        conn = self._get_conn()
        conn.execute("UPDATE alarm_records SET acknowledged = 1 WHERE id = ?", (alarm_id,))
        conn.commit()

    def get_latest_value(self, device_id: str, point_name: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT * FROM data_records WHERE device_id = ? AND point_name = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (device_id, point_name)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_device_latest(self, device_id: str) -> Dict[str, Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT point_name, value, unit, timestamp, success, is_alarm
               FROM data_records WHERE device_id = ?
               GROUP BY point_name
               ORDER BY timestamp DESC""",
            (device_id,)
        )
        result = {}
        for row in cursor.fetchall():
            result[row['point_name']] = dict(row)
        return result

    def query_data_filtered(self, device_id: Optional[str] = None, point_name: Optional[str] = None,
                        start_time: Optional[float] = None, end_time: Optional[float] = None,
                        status: Optional[int] = None, is_alarm: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        sql = "SELECT * FROM data_records WHERE 1=1"
        params = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        if point_name:
            sql += " AND point_name = ?"
            params.append(point_name)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        if status is not None:
            sql += " AND success = ?"
            params.append(status)
        if is_alarm is not None:
            sql += " AND is_alarm = ?"
            params.append(is_alarm)
        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def count_data_filtered(self, device_id: Optional[str] = None, point_name: Optional[str] = None,
                            start_time: Optional[float] = None, end_time: Optional[float] = None,
                            status: Optional[int] = None, is_alarm: Optional[int] = None) -> int:
        conn = self._get_conn()
        sql = "SELECT COUNT(*) as cnt FROM data_records WHERE 1=1"
        params = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        if point_name:
            sql += " AND point_name = ?"
            params.append(point_name)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        if status is not None:
            sql += " AND success = ?"
            params.append(status)
        if is_alarm is not None:
            sql += " AND is_alarm = ?"
            params.append(is_alarm)
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return row['cnt'] if row else 0

    def get_statistics(self, device_id: Optional[str] = None,
                       start_time: Optional[float] = None, end_time: Optional[float] = None) -> Dict[str, Any]:
        conn = self._get_conn()
        sql = "SELECT COUNT(*) as total, SUM(success) as success_count FROM data_records WHERE 1=1"
        params = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        total = row['total'] or 0
        success_count = row['success_count'] or 0
        return {
            'total_records': total,
            'success_count': success_count,
            'fail_count': total - success_count,
            'success_rate': (success_count / total * 100) if total > 0 else 100.0
        }

    def delete_old_data(self, before_timestamp: float):
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM data_records WHERE timestamp < ?", (before_timestamp,))
            conn.execute("DELETE FROM alarm_records WHERE timestamp < ?", (before_timestamp,))
            conn.commit()
        log_manager.info("数据库", f"已清理 {before_timestamp} 之前的旧数据")

    def export_csv(self, filepath: str, device_id: Optional[str] = None,
                   start_time: Optional[float] = None, end_time: Optional[float] = None):
        records = self.query_data(device_id=device_id, start_time=start_time, end_time=end_time, limit=1000000)
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            if records:
                writer = csv.DictWriter(f, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
        log_manager.info("数据库", f"已导出 {len(records)} 条记录到 {filepath}")

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


db = Database()