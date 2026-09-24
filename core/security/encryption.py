import os
import base64
import hashlib
import tempfile
from typing import Optional, Dict
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
from config.config_manager import CONFIG_DIR


class AESEncryptor:
    _MAGIC = b"IIOT-GCM1"
    _NONCE_SIZE = 12
    _TAG_SIZE = 16

    def __init__(self, key: Optional[bytes] = None, key_size: int = 32):
        if key is None:
            key = get_random_bytes(key_size)
        elif len(key) not in (16, 24, 32):
            key = hashlib.sha256(key).digest()[:key_size]
        self._key = key

    def encrypt(self, data: bytes) -> bytes:
        nonce = get_random_bytes(self._NONCE_SIZE)
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        encrypted, tag = cipher.encrypt_and_digest(data)
        return self._MAGIC + nonce + tag + encrypted

    def decrypt(self, data: bytes) -> bytes:
        if data.startswith(self._MAGIC):
            header_size = len(self._MAGIC)
            nonce_start = header_size
            tag_start = nonce_start + self._NONCE_SIZE
            payload_start = tag_start + self._TAG_SIZE
            nonce = data[nonce_start:tag_start]
            tag = data[tag_start:payload_start]
            encrypted = data[payload_start:]
            if len(nonce) != self._NONCE_SIZE or len(tag) != self._TAG_SIZE:
                raise ValueError("加密数据格式无效")
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(encrypted, tag)

        # Backward-compatible read path for data written by v1.0 CBC mode.
        iv = data[:16]
        encrypted = data[16:]
        if len(iv) != 16 or not encrypted or len(encrypted) % AES.block_size:
            raise ValueError("加密数据格式无效")
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
        self._aes: Optional[AESEncryptor] = None
        self._enabled = False

    def set_key(self, key: bytes):
        self._aes = AESEncryptor(key=key)

    def _load_key(self) -> bytes:
        configured = os.getenv("IIOT_GATEWAY_ENCRYPTION_KEY", "").strip()
        if configured:
            try:
                decoded = base64.urlsafe_b64decode(configured.encode("ascii"))
                if len(decoded) in (16, 24, 32):
                    return decoded
            except (ValueError, UnicodeEncodeError):
                pass
            return configured.encode("utf-8")

        key_path = os.path.join(CONFIG_DIR, "encryption.key")
        if os.path.exists(key_path):
            with open(key_path, "rb") as handle:
                key = handle.read()
            if len(key) not in (16, 24, 32):
                raise ValueError("本地加密密钥长度无效")
            return key

        key = get_random_bytes(32)
        key_dir = os.path.dirname(key_path)
        os.makedirs(key_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="encryption.", suffix=".tmp", dir=key_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, key_path)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return key

    def _ensure_key(self):
        if self._aes is None:
            self._aes = AESEncryptor(key=self._load_key())

    def enable(self):
        self._ensure_key()
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
        self._ensure_key()
        decrypted = self._aes.decrypt_string(data['data'])
        return json.loads(decrypted)

    def encrypt(self, text: str) -> str:
        if self._enabled:
            return self._aes.encrypt_string(text)
        return text

    def decrypt(self, encoded: str) -> str:
        if self._enabled:
            self._ensure_key()
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
