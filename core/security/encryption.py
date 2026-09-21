import os
import base64
import hashlib
from typing import Optional, Dict
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes


class AESEncryptor:
    def __init__(self, key: Optional[bytes] = None, key_size: int = 16):
        if key is None:
            key = get_random_bytes(key_size)
        elif len(key) not in (16, 24, 32):
            key = hashlib.sha256(key).digest()[:key_size]
        self._key = key[:key_size]

    def encrypt(self, data: bytes) -> bytes:
        iv = get_random_bytes(16)
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(pad(data, AES.block_size))
        return iv + encrypted

    def decrypt(self, data: bytes) -> bytes:
        iv = data[:16]
        encrypted = data[16:]
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(encrypted), AES.block_size)

    def encrypt_string(self, text: str) -> str:
        encrypted = self.encrypt(text.encode('utf-8'))
        return base64.b64encode(encrypted).decode('ascii')

    def decrypt_string(self, encoded: str) -> str:
        encrypted = base64.b64decode(encoded.encode('ascii'))
        return self.decrypt(encrypted).decode('utf-8')

    def encrypt_file(self, input_path: str, output_path: Optional[str] = None):
        if output_path is None:
            output_path = input_path + '.enc'
        with open(input_path, 'rb') as f:
            plaintext = f.read()
        ciphertext = self.encrypt(plaintext)
        with open(output_path, 'wb') as f:
            f.write(ciphertext)

    def decrypt_file(self, input_path: str, output_path: Optional[str] = None):
        if output_path is None:
            output_path = input_path.replace('.enc', '.dec')
        with open(input_path, 'rb') as f:
            ciphertext = f.read()
        plaintext = self.decrypt(ciphertext)
        with open(output_path, 'wb') as f:
            f.write(plaintext)


class DataEncryptor:
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
        default_key = b'IIoTGatewayKey12'
        self._aes = AESEncryptor(key=default_key)
        self._enabled = False

    def set_key(self, key: bytes):
        self._aes = AESEncryptor(key=key)

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def encrypt_data(self, data: Dict) -> Dict:
        if not self._enabled:
            return data
        import json
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = self._aes.encrypt_string(json_str)
        return {'encrypted': True, 'data': encrypted}

    def decrypt_data(self, data: Dict) -> Dict:
        if not data.get('encrypted'):
            return data
        import json
        decrypted = self._aes.decrypt_string(data['data'])
        return json.loads(decrypted)

    def encrypt(self, text: str) -> str:
        if self._enabled:
            return self._aes.encrypt_string(text)
        return text

    def decrypt(self, encoded: str) -> str:
        if self._enabled:
            return self._aes.decrypt_string(encoded)
        return encoded


def hash_password(password: str, salt: Optional[str] = None) -> tuple:
    if salt is None:
        salt = base64.b64encode(os.urandom(16)).decode('ascii')
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('ascii'), 100000)
    return base64.b64encode(hashed).decode('ascii'), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    new_hash, _ = hash_password(password, salt)
    return new_hash == hashed


data_encryptor = DataEncryptor()