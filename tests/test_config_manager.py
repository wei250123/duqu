import unittest

from config.config_manager import (
    AppConfig,
    BackupMqttConfig,
    CollectPoint,
    DeviceConfig,
    _dict_to_dataclass,
)


class ConfigDeserializationTests(unittest.TestCase):
    def test_missing_fields_use_dataclass_defaults(self):
        app_config = _dict_to_dataclass({}, AppConfig)
        device_config = _dict_to_dataclass({}, DeviceConfig)

        self.assertEqual(app_config.language, "zh_CN")
        self.assertEqual(app_config.log.level, "INFO")
        self.assertEqual(app_config.backup_servers, [])
        self.assertEqual(device_config.serial.port, "")
        self.assertEqual(device_config.collect.points, [])

    def test_nested_dataclasses_and_lists_are_converted(self):
        app_config = _dict_to_dataclass(
            {"backup_servers": [{"host": "backup.example.com", "port": 8883}]},
            AppConfig,
        )
        device_config = _dict_to_dataclass(
            {
                "device_id": "device-1",
                "collect": {
                    "points": [{"name": "temperature", "register_address": 10}]
                },
            },
            DeviceConfig,
        )

        self.assertIsInstance(app_config.backup_servers[0], BackupMqttConfig)
        self.assertEqual(app_config.backup_servers[0].port, 8883)
        self.assertIsInstance(device_config.collect.points[0], CollectPoint)
        self.assertEqual(device_config.collect.points[0].register_address, 10)


if __name__ == "__main__":
    unittest.main()
