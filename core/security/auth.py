import os
import time
import hashlib
import base64
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from config.config_manager import config_manager
from core.security.encryption import hash_password, verify_password
from utils.logger import log_manager


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
        self._init_default_users()
        self._operation_logs: List[dict] = []

    def _init_default_users(self):
        default_hash, default_salt = hash_password("admin123")
        self._users["admin"] = User(
            username="admin",
            password_hash=default_hash,
            salt=default_salt,
            role=Role.ADMIN
        )
        op_hash, op_salt = hash_password("operator123")
        self._users["operator"] = User(
            username="operator",
            password_hash=op_hash,
            salt=op_salt,
            role=Role.OPERATOR
        )
        viewer_hash, viewer_salt = hash_password("viewer123")
        self._users["viewer"] = User(
            username="viewer",
            password_hash=viewer_hash,
            salt=viewer_salt,
            role=Role.VIEWER
        )

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
        pwd_hash, pwd_salt = hash_password(password)
        self._users[username] = User(username=username, password_hash=pwd_hash, salt=pwd_salt, role=role)
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
        self._log_operation(self._current_user.username, "remove_user", True, f"删除用户 {username}")
        return True, "用户删除成功"

    def change_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        user = self._users.get(username)
        if not user:
            return False, "用户不存在"
        if not verify_password(old_password, user.password_hash, user.salt):
            return False, "原密码错误"
        pwd_hash, pwd_salt = hash_password(new_password)
        user.password_hash = pwd_hash
        user.salt = pwd_salt
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
        if not app_cfg.startup_password:
            return True
        return password == app_cfg.startup_password


auth_manager = AuthManager()