import unittest
from unittest.mock import patch

from config.config_manager import ApiConfig, AppConfig
from core.runtime.gateway_runtime import GatewayRuntime


class GatewayRuntimeTests(unittest.TestCase):
    def test_lifecycle_owns_maintenance_and_collection(self):
        config = AppConfig(auto_start_collect=True, api=ApiConfig(enabled=False))
        runtime = GatewayRuntime(config)
        with patch("core.runtime.gateway_runtime.db.start_maintenance") as start_db, \
                patch("core.runtime.gateway_runtime.db.stop_maintenance") as stop_db, \
                patch("core.runtime.gateway_runtime.device_manager.start_all") as start_devices, \
                patch("core.runtime.gateway_runtime.device_manager.stop_all") as stop_devices, \
                patch("core.runtime.gateway_runtime.cache_manager.stop_upload_worker") as stop_cache:
            self.assertTrue(runtime.start())
            self.assertTrue(runtime.is_running)
            start_db.assert_called_once_with(config.data_retention_days)

            runtime.start_collection()
            start_devices.assert_called_once_with()

            runtime.stop()
            self.assertFalse(runtime.is_running)
            stop_devices.assert_called_once_with()
            stop_cache.assert_called_once_with()
            stop_db.assert_called_once_with()

            # Shutdown is safe to call from both Qt close and atexit paths.
            runtime.stop()
            self.assertEqual(stop_db.call_count, 1)

    def test_collection_requires_started_runtime(self):
        config = AppConfig(auto_start_collect=True, api=ApiConfig(enabled=False))
        runtime = GatewayRuntime(config)
        with self.assertRaises(RuntimeError):
            runtime.start_collection()


if __name__ == "__main__":
    unittest.main()
