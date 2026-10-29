"""Landing page."""
from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, url_for

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("cycles.dashboard"))
    return render_template("index.html")
