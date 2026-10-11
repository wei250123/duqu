import os
import tempfile
import threading
import unittest

from config.config_manager import CacheConfig
from core.storage.cache_manager import cache_manager
from core.storage.database import db


class CacheStorageTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path = db._db_path
        self._old_local = db._local
        self._temp_dir = tempfile.TemporaryDirectory()
        db._db_path = os.path.join(self._temp_dir.name, "gateway.db")
        db._local = threading.local()
        db._init_tables()
        cache_manager.stop_upload_worker()
        cache_manager._configs.clear()
        cache_manager._upload_callbacks.clear()

    def tearDown(self):
        cache_manager.stop_upload_worker()
        cache_manager._configs.clear()
        cache_manager._upload_callbacks.clear()
        db.close()
        db._db_path = self._old_db_path
        db._local = self._old_local
        self._temp_dir.cleanup()

    def test_latest_value_uses_timestamp_then_id(self):
        db.insert_data("device", "temperature", 1.0, timestamp=100)
        db.insert_data("device", "temperature", 2.0, timestamp=100)
        latest = db.get_device_latest("device")
        self.assertEqual(latest["temperature"]["value"], 2.0)

    def test_cache_retries_backoff_and_dead_letter(self):
        config = CacheConfig(
            max_records=10,
            max_retries=2,
            retry_backoff_seconds=0.01,
            max_backoff_seconds=0.01,
        )
        cache_manager.register_device("device", config, lambda records: False)
        self.assertTrue(cache_manager.cache_data("device", "topic", "payload"))

        cache_manager._process_cached_data()
        status = cache_manager.get_cache_status("device")
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["dead_letter"], 0)

        db._get_conn().execute(
            "UPDATE upload_cache SET next_retry_at = 0 WHERE device_id = ?",
            ("device",),
        )
        db._get_conn().commit()
        cache_manager._process_cached_data()
        status = cache_manager.get_cache_status("device")
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["dead_letter"], 1)

    def test_successful_upload_removes_queue_rows(self):
        cache_manager.register_device("device", CacheConfig(), lambda records: True)
        self.assertTrue(cache_manager.cache_data("device", "topic", "payload"))
        cache_manager._process_cached_data()
        self.assertEqual(cache_manager.get_cache_status("device")["total"], 0)


if __name__ == "__main__":
    unittest.main()
