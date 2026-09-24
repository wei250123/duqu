import os
import time
import json
import hmac
import tempfile
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from config.config_manager import CONFIG_DIR, config_manager
from core.security.encryption import hash_password, verify_password
from utils.logger import log_manager


USER_FILE = os.path.join(CONFIG_DIR, "users.json")
MIN_PASSWORD_LENGTH = 8


@dataclass
class User:
    username: str
    password_hash: str
    salt: str
    role: str = "operator"
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_login: float = 0.0

    def to_dict(self) -> dict:
        return {
            'username': self.username,
            'password_hash': self.password_hash,
            'salt': self.salt,
            'role': self.role,
            'enabled': self.enabled,
            'created_at': self.created_at,
            'last_login': self.last_login
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        return cls(
            username=data['username'],
            password_hash=data['password_hash'],
            salt=data['salt'],
            role=data.get('role', 'operator'),
            enabled=data.get('enabled', True),
            created_at=data.get('created_at', time.time()),
            last_login=data.get('last_login', 0.0)
        )


class Role:
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

    PERMISSIONS = {
        ADMIN: {
            'modify_config': True, 'control_device': True, 'view_data': True,
            'export_data': True, 'manage_users': True, 'debug_tools': True,
            'system_settings': True
        },
        OPERATOR: {
            'modify_config': False, 'control_device': True, 'view_data': True,
            'export_data': True, 'manage_users': False, 'debug_tools': False,
            'system_settings': False
        },
        VIEWER: {
            'modify_config': False, 'control_device': False, 'view_data': True,
            'export_data': False, 'manage_users': False, 'debug_tools': False,
            'system_settings': False
        }
    }

    @classmethod
    def has_permission(cls, role: str, permission: str) -> bool:
        return cls.PERMISSIONS.get(role, {}).get(permission, False)


class AuthManager:
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
        self._users: Dict[str, User] = {}
        self._current_user: Optional[User] = None
        self._logged_in = False
        self._operation_logs: List[dict] = []
        self._load_users()

    def _default_users(self) -> Dict[str, User]:
        default_hash, default_salt = hash_password("admin123")
        users = {"admin": User(
            username="admin",
            password_hash=default_hash,
            salt=default_salt,
            role=Role.ADMIN
        )}
        op_hash, op_salt = hash_password("operator123")
        users["operator"] = User(
            username="operator",
            password_hash=op_hash,
            salt=op_salt,
            role=Role.OPERATOR
        )
        viewer_hash, viewer_salt = hash_password("viewer123")
        users["viewer"] = User(
            username="viewer",
            password_hash=viewer_hash,
            salt=viewer_salt,
            role=Role.VIEWER
        )
        return users

    def _load_users(self):
        if not os.path.exists(USER_FILE):
            self._users = self._default_users()
            self._save_users()
            log_manager.warn("安全", "首次启动已创建默认账户，请立即修改默认密码")
            return
        try:
            with open(USER_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            users = {}
            for username, user_data in data.items():
                user = User.from_dict(user_data)
                if username == user.username and user.role in Role.PERMISSIONS:
                    users[username] = user
            self._users = users
            if not self._users:
                log_manager.error("安全", "用户配置为空或无有效账户，登录将被拒绝")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._users = {}
            log_manager.error("安全", f"用户配置读取失败，登录将被拒绝: {exc}")

    def _save_users(self):
        user_dir = os.path.dirname(USER_FILE) or CONFIG_DIR
        os.makedirs(user_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="users.", suffix=".tmp", dir=user_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {username: user.to_dict() for username, user in self._users.items()},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, USER_FILE)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @staticmethod
    def _validate_password(password: str) -> Tuple[bool, str]:
        if len(password) < MIN_PASSWORD_LENGTH:
            return False, f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 位"
        return True, ""

    def login(self, username: str, password: str) -> Tuple[bool, str]:
        user = self._users.get(username)
        if not user:
            self._log_operation(username, "login", False, "用户不存在")
            return False, "用户名或密码错误"
        if not user.enabled:
            self._log_operation(username, "login", False, "账户已禁用")
            return False, "账户已被禁用，请联系管理员"
        if verify_password(password, user.password_hash, user.salt):
            self._current_user = user
            self._logged_in = True
            user.last_login = time.time()
            self._save_users()
            self._log_operation(username, "login", True, f"登录成功，角色: {user.role}")
            log_manager.info("安全", f"用户 {username} 登录成功")
            return True, "登录成功"
        self._log_operation(username, "login", False, "密码错误")
        return False, "用户名或密码错误"

    def logout(self):
        if self._current_user:
            self._log_operation(self._current_user.username, "logout", True)
            log_manager.info("安全", f"用户 {self._current_user.username} 登出")
        self._current_user = None
        self._logged_in = False

    def is_logged_in(self) -> bool:
        return self._logged_in and self._current_user is not None

    def get_current_user(self) -> Optional[User]:
        return self._current_user

    def get_current_role(self) -> str:
        return self._current_user.role if self._current_user else ""

    def has_permission(self, permission: str) -> bool:
        if not self._current_user:
            return False
        return Role.has_permission(self._current_user.role, permission)

    def add_user(self, username: str, password: str, role: str = "operator") -> Tuple[bool, str]:
        if not self.has_permission('manage_users'):
            return False, "无权限添加用户"
        if username in self._users:
            return False, "用户名已存在"
        if role not in Role.PERMISSIONS:
            return False, f"无效的角色: {role}"
        valid, error = self._validate_password(password)
        if not valid:
            return False, error
        pwd_hash, pwd_salt = hash_password(password)
        self._users[username] = User(username=username, password_hash=pwd_hash, salt=pwd_salt, role=role)
        self._save_users()
        self._log_operation(self._current_user.username, "add_user", True, f"添加用户 {username}")
        return True, "用户添加成功"

    def remove_user(self, username: str) -> Tuple[bool, str]:
        if not self.has_permission('manage_users'):
            return False, "无权限删除用户"
        if username == "admin":
            return False, "不能删除管理员账户"
        if username not in self._users:
            return False, "用户不存在"
        del self._users[username]
        self._save_users()
        self._log_operation(self._current_user.username, "remove_user", True, f"删除用户 {username}")
        return True, "用户删除成功"

    def change_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        user = self._users.get(username)
        if not user:
            return False, "用户不存在"
        if (not self._current_user or
                (self._current_user.username != username and
                 not self.has_permission('manage_users'))):
            return False, "无权限修改该用户密码"
        if not verify_password(old_password, user.password_hash, user.salt):
            return False, "原密码错误"
        valid, error = self._validate_password(new_password)
        if not valid:
            return False, error
        pwd_hash, pwd_salt = hash_password(new_password)
        user.password_hash = pwd_hash
        user.salt = pwd_salt
        self._save_users()
        self._log_operation(username, "change_password", True)
        return True, "密码修改成功"

    def get_all_users(self) -> List[User]:
        return list(self._users.values())

    def _log_operation(self, username: str, action: str, success: bool, detail: str = ""):
        entry = {
            'timestamp': time.time(),
            'username': username,
            'action': action,
            'success': success,
            'detail': detail
        }
        self._operation_logs.append(entry)
        if len(self._operation_logs) > 10000:
            self._operation_logs = self._operation_logs[-5000:]

    def get_operation_logs(self, limit: int = 500) -> List[dict]:
        return self._operation_logs[-limit:]

    def verify_startup_password(self, password: str) -> bool:
        app_cfg = config_manager.app_config
        if not self.has_startup_password():
            return True
        if app_cfg.startup_password_hash and app_cfg.startup_password_salt:
            return verify_password(
                password, app_cfg.startup_password_hash, app_cfg.startup_password_salt
            )
        # Migrate legacy plaintext configuration after a successful check.
        valid = hmac.compare_digest(password, app_cfg.startup_password)
        if valid:
            self.set_startup_password(password)
        return valid

    def has_startup_password(self) -> bool:
        app_cfg = config_manager.app_config
        return bool(
            (app_cfg.startup_password_hash and app_cfg.startup_password_salt)
            or app_cfg.startup_password
        )

    def set_startup_password(self, password: str) -> Tuple[bool, str]:
        if password:
            valid, error = self._validate_password(password)
            if not valid:
                return False, error
            pwd_hash, pwd_salt = hash_password(password)
            config_manager.app_config.startup_password_hash = pwd_hash
            config_manager.app_config.startup_password_salt = pwd_salt
            config_manager.app_config.startup_password = ""
        else:
            config_manager.app_config.startup_password = ""
            config_manager.app_config.startup_password_hash = ""
            config_manager.app_config.startup_password_salt = ""
        config_manager.save_app_config()
        return True, "启动密码设置成功"


auth_manager = AuthManager()
