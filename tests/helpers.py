"""Shared test scaffolding (stdlib unittest only, no third-party test dependencies)."""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from skillpath import create_app


class AppTestCase(unittest.TestCase):
    csrf_disabled = True

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="skillpath-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(self.tmp / "test.sqlite"),
                "UPLOAD_DIR": str(self.tmp / "uploads"),
                "CSRF_DISABLED": self.csrf_disabled,
            }
        )
        self.client = self.app.test_client()

    # -- auth helpers -------------------------------------------------------
    def register(self, username="herb", password="correct horse"):
        return self.client.post("/register", data={"username": username, "password": password},
                                follow_redirects=True)

    def login(self, username="herb", password="correct horse"):
        return self.client.post("/login", data={"username": username, "password": password},
                                follow_redirects=True)

    def logout(self):
        return self.client.post("/logout", follow_redirects=True)


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()
