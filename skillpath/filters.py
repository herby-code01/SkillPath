"""Jinja filters. Dates are stored in UTC and shown in the browser's timezone.

static/app.js stores the browser's UTC offset in a `tzo` cookie (minutes, as returned by
Date.getTimezoneOffset()). Without the cookie (first visit, no JS) UTC is used.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Flask, request

from .db import from_iso


def local_dt(value: str | datetime) -> datetime:
    dt = from_iso(value) if isinstance(value, str) else value
    offset = request.cookies.get("tzo", type=int)
    if offset is not None and -840 <= offset <= 840:
        dt = dt - timedelta(minutes=offset)
    return dt


def fmtdate(value: str | datetime | date) -> str:
    if isinstance(value, str) or isinstance(value, datetime):
        value = local_dt(value)
    return f"{value:%a, %b} {value.day}"


def fmtdatetime(value: str | datetime) -> str:
    dt = local_dt(value)
    hour = dt.hour % 12 or 12
    return f"{dt:%b} {dt.day}, {hour}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def init_app(app: Flask) -> None:
    app.jinja_env.filters["fmtdate"] = fmtdate
    app.jinja_env.filters["fmtdatetime"] = fmtdatetime
