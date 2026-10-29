"""Registration, login, logout, and the login_required decorator."""
from __future__ import annotations

import functools
import re

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, to_iso, utcnow
from .security import is_safe_next

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MIN_PASSWORD = 8


@bp.before_app_request
def load_user() -> None:
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = None
        if not USERNAME_RE.match(username):
            error = "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
        elif len(password) < MIN_PASSWORD:
            error = f"Password must be at least {MIN_PASSWORD} characters."
        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), to_iso(utcnow())),
                )
                db.commit()
            except Exception:  # sqlite3.IntegrityError on duplicate username
                db.rollback()
                error = "That username is taken."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                return redirect(url_for("main.index"))
        flash(error, "error")
    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}:{username.lower()}"
        throttle = current_app.extensions["login_throttle"]
        if throttle.blocked(key):
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
            return render_template("auth/login.html"), 429
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            throttle.record_failure(key)
            flash("Incorrect username or password.", "error")
        else:
            throttle.reset(key)
            session.clear()
            session["user_id"] = user["id"]
            target = request.args.get("next")
            return redirect(target if is_safe_next(target) else url_for("main.index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("main.index"))
