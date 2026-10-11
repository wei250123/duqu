import unittest
from unittest.mock import patch

from config.config_manager import CacheConfig, MqttConfig
from core.mqtt.mqtt_client import MqttClient, mqtt_manager
from core.storage.cache_manager import cache_manager


class CacheRegistrationTests(unittest.TestCase):
    def tearDown(self):
        mqtt_manager.remove_client("cache-registration-test")
        cache_manager._configs.pop("cache-registration-test", None)
        cache_manager._upload_callbacks.pop("cache-registration-test", None)

    def test_device_cache_config_is_registered_with_mqtt_connection(self):
        cache_config = CacheConfig(max_records=7)
        config = MqttConfig(auto_reconnect=False)
        with patch.object(MqttClient, "connect", return_value=False):
            mqtt_manager.connect_device("cache-registration-test", config, cache_config)
        self.assertEqual(
            cache_manager._configs["cache-registration-test"].max_records,
            7,
        )


if __name__ == "__main__":
    unittest.main()
