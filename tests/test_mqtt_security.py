import ssl
import unittest

from config.config_manager import MqttConfig
from core.mqtt.mqtt_client import MqttClient


class MqttSecurityTests(unittest.TestCase):
    def test_tls_context_verifies_server_certificates_by_default(self):
        client = MqttClient(MqttConfig(use_tls=True), "test-device")
        context = client._build_tls_context()

        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
