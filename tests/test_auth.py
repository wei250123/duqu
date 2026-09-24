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


if __name__ == "__main__":
    unittest.main()
