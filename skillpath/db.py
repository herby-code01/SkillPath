"""SQLite helpers. One connection per request, closed on teardown."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from importlib import resources

import click
from flask import Flask, current_app, g


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    schema = resources.files("skillpath").joinpath("schema.sql").read_text(encoding="utf-8")
    db = get_db()
    db.executescript(schema)
    db.commit()


@click.command("init-db")
def init_db_command() -> None:
    """Create any missing tables."""
    init_db()
    click.echo("Database ready.")


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    with app.app_context():
        init_db()
