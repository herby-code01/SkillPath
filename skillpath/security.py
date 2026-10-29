"""CSRF protection and a tiny login throttle."""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

from flask import Flask, abort, request, session
from markupsafe import Markup

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def csrf_field() -> Markup:
    return Markup('<input type="hidden" name="csrf_token" value="%s">') % csrf_token()


def init_csrf(app: Flask) -> None:
    @app.before_request
    def _check_csrf() -> None:
        if request.method in _SAFE_METHODS or app.config.get("CSRF_DISABLED"):
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not expected or not secrets.compare_digest(sent, expected):
            abort(400, description="Missing or invalid CSRF token. Reload the page and try again.")

    app.jinja_env.globals["csrf_field"] = csrf_field


class LoginThrottle:
    """Allow `limit` failed attempts per key inside `window` seconds (in-memory, per process)."""

    def __init__(self, limit: int = 5, window: int = 300) -> None:
        self.limit = limit
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._fails[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def record_failure(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


def is_safe_next(target: str | None) -> bool:
    """Only allow same-site relative redirects."""
    return bool(target) and target.startswith("/") and not target.startswith("//") and "\\" not in target
