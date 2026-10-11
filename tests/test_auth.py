import os
import tempfile
import unittest
from unittest.mock import patch

import core.security.auth as auth_module


class AuthPersistenceTests(unittest.TestCase):
    def test_users_persist_and_password_policy_is_enforced(self):
        original_instance = auth_module.AuthManager._instance
        with tempfile.TemporaryDirectory() as temp_dir:
            user_file = os.path.join(temp_dir, "users.json")
            try:
                with patch.object(auth_module, "USER_FILE", user_file):
                    auth_module.AuthManager._instance = None
                    manager = auth_module.AuthManager()

                    self.assertTrue(manager.login("admin", "admin123")[0])
                    self.assertFalse(manager.add_user("weak", "short")[0])
                    self.assertTrue(manager.add_user("alice", "alicepass", "viewer")[0])

                    auth_module.AuthManager._instance = None
                    reloaded = auth_module.AuthManager()
                    self.assertTrue(reloaded.login("alice", "alicepass")[0])
                    self.assertEqual(reloaded.get_current_role(), "viewer")
            finally:
                auth_module.AuthManager._instance = original_instance

    def test_failed_logins_lock_account_and_write_audit_event(self):
        original_instance = auth_module.AuthManager._instance
        with tempfile.TemporaryDirectory() as temp_dir:
            user_file = os.path.join(temp_dir, "users.json")
            audit_file = os.path.join(temp_dir, "security_audit.jsonl")
            try:
                with patch.object(auth_module, "USER_FILE", user_file), \
                        patch.object(auth_module, "AUDIT_FILE", audit_file), \
                        patch.object(auth_module, "MAX_FAILED_ATTEMPTS", 2), \
                        patch.object(auth_module, "LOCKOUT_SECONDS", 60):
                    auth_module.AuthManager._instance = None
                    manager = auth_module.AuthManager()

                    self.assertFalse(manager.login("admin", "wrong-one")[0])
                    locked, message = manager.login("admin", "wrong-two")
                    self.assertFalse(locked)
                    self.assertIn("锁定", message)
                    self.assertFalse(manager.login("admin", "admin123")[0])

                    with open(audit_file, "r", encoding="utf-8") as handle:
                        audit = handle.read()
                    self.assertIn('"action": "login"', audit)
                    self.assertIn("账户已锁定", audit)
            finally:
                auth_module.AuthManager._instance = original_instance


if __name__ == "__main__":
    unittest.main()
