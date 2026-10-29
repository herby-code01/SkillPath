import unittest

from skillpath import create_app
from skillpath.security import LoginThrottle, is_safe_next

from .helpers import AppTestCase


class AuthTests(AppTestCase):
    def test_landing_page_renders(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"SkillPath", res.data)

    def test_register_logout_login(self):
        res = self.register()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"herb", res.data)  # username shown in nav
        self.logout()
        self.assertIn(b"Log in", self.client.get("/").data)
        self.assertIn(b"herb", self.login().data)

    def test_register_validation(self):
        res = self.client.post("/register", data={"username": "ok_name", "password": "short"})
        self.assertIn(b"at least 8", res.data)
        res = self.client.post("/register", data={"username": "no spaces!", "password": "longenough1"})
        self.assertIn(b"Username must be", res.data)

    def test_duplicate_username_rejected_case_insensitively(self):
        self.register("Herb")
        self.logout()
        self.assertIn(b"taken", self.register("herb").data)

    def test_wrong_password_fails(self):
        self.register()
        self.logout()
        self.assertIn(b"Incorrect username or password", self.login(password="wrong-password").data)

    def test_login_throttled_after_repeated_failures(self):
        self.register()
        self.logout()
        for _ in range(5):
            self.client.post("/login", data={"username": "herb", "password": "nope-nope"})
        res = self.client.post("/login", data={"username": "herb", "password": "correct horse"})
        self.assertEqual(res.status_code, 429)


class CsrfTests(unittest.TestCase):
    def test_csrf_enforced_when_enabled(self):
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        app = create_app({"TESTING": True, "SECRET_KEY": "k", "DATABASE": f"{tmp}/c.sqlite"})
        res = app.test_client().post("/register", data={"username": "abc", "password": "longenough1"})
        self.assertEqual(res.status_code, 400)


class HelperTests(unittest.TestCase):
    def test_open_redirect_helper(self):
        self.assertTrue(is_safe_next("/dashboard"))
        self.assertFalse(is_safe_next("//evil.example"))
        self.assertFalse(is_safe_next("https://evil.example"))
        self.assertFalse(is_safe_next("/\\evil.example"))
        self.assertFalse(is_safe_next(None))

    def test_throttle_window_expires(self):
        t = LoginThrottle(limit=2, window=0)
        t.record_failure("k")
        t.record_failure("k")
        self.assertFalse(t.blocked("k"))  # 0s window: failures age out immediately


if __name__ == "__main__":
    unittest.main()
