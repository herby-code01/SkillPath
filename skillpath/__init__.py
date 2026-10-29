"""SkillPath: project-driven learning with concept primers, LeetCode links and automated review."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, render_template

__version__ = "1.0.0"


def _load_or_create_secret(instance_dir: Path) -> str:
    """Persist a random secret key in the instance folder so sessions survive restarts."""
    path = instance_dir / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SKILLPATH_SECRET_KEY") or _load_or_create_secret(instance),
        DATABASE=str(instance / "skillpath.sqlite"),
        UPLOAD_DIR=str(instance / "uploads"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        PASS_SCORE=70,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        APP_VERSION=__version__,
    )
    if test_config:
        app.config.update(test_config)

    from . import auth, cycles, db, filters, learn, security, submissions, views

    app.extensions["login_throttle"] = security.LoginThrottle()  # per-process, per-app
    db.init_app(app)
    security.init_csrf(app)
    filters.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    app.register_blueprint(cycles.bp)
    app.register_blueprint(submissions.bp)
    app.register_blueprint(learn.bp)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def _client_error(err):
        message = {
            404: "That page does not exist.",
            413: "That upload is too large (limit is 5 MB).",
        }.get(err.code, getattr(err, "description", "Bad request."))
        return render_template("error.html", code=err.code, message=message), err.code

    return app
