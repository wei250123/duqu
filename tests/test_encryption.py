import os
import tempfile
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES

import core.security.encryption as encryption_module


class EncryptionTests(unittest.TestCase):
    def test_aes_gcm_roundtrip_and_tamper_detection(self):
        encryptor = encryption_module.AESEncryptor(key=b"test-key")
        encrypted = encryptor.encrypt(b"industrial telemetry")

        self.assertTrue(encrypted.startswith(encryption_module.AESEncryptor._MAGIC))
        self.assertEqual(encryptor.decrypt(encrypted), b"industrial telemetry")

        tampered = bytearray(encrypted)
        tampered[-1] ^= 1
        with self.assertRaises(ValueError):
            encryptor.decrypt(bytes(tampered))

    def test_data_encryptor_generates_runtime_key_without_fixed_default(self):
        original_instance = encryption_module.DataEncryptor._instance
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                with patch.object(encryption_module, "CONFIG_DIR", temp_dir), \
                        patch.dict(os.environ, {"IIOT_GATEWAY_ENCRYPTION_KEY": ""}, clear=False):
                    os.environ.pop("IIOT_GATEWAY_ENCRYPTION_KEY", None)
                    encryption_module.DataEncryptor._instance = None
                    encryptor = encryption_module.DataEncryptor()
                    encryptor.enable()
                    encoded = encryptor.encrypt("secret")
                    self.assertEqual(encryptor.decrypt(encoded), "secret")
                    key_path = os.path.join(temp_dir, "encryption.key")
                    self.assertTrue(os.path.exists(key_path))
                    self.assertEqual(os.path.getsize(key_path), AES.block_size * 2)
            finally:
                encryption_module.DataEncryptor._instance = original_instance


if __name__ == "__main__":
    unittest.main()
