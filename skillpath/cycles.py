"""Project cycles: dashboard, roadmap, project pages, start / extend / abandon, settings."""
from __future__ import annotations

import math
from datetime import timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

from . import content
from .auth import login_required
from .db import from_iso, get_db, to_iso, utcnow
from .filters import local_dt
from .mastery import READY_THRESHOLD, project_readiness
from .planning import build_schedule, sprint_problems, sprint_quota
from .progress import load_progress, load_state
from .recommender import eligible_projects, locked_reasons, recommend_next

bp = Blueprint("cycles", __name__)

MIN_WEEKS, MAX_WEEKS = 1, 12


def _state(db):
    return load_state(db, g.user)


def _timing(assignment) -> dict:
    now = utcnow()
    start, due = from_iso(assignment["started_at"]), from_iso(assignment["due_at"])
    total = max((due - start).total_seconds(), 1)
    seconds_left = (due - now).total_seconds()
    return {
        "start": local_dt(start),
        "due": local_dt(due),
        "pct_time": max(0, min(100, round((now - start).total_seconds() / total * 100))),
        "days_left": math.ceil(seconds_left / 86400),
        "overdue": seconds_left < 0,
    }


def _own_open_assignment(db, assignment_id: int):
    row = db.execute("SELECT * FROM assignments WHERE id = ? AND user_id = ?",
                     (assignment_id, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    if row["status"] not in ("active", "needs_revision"):
        flash("That project cycle is already closed.", "error")
        return None
    return row


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    track, progress, mastery = _state(db)
    ctx = {"track": track, "progress": progress, "mastery": mastery, "ready_threshold": READY_THRESHOLD}

    assignment = progress.open_assignment
    if assignment:
        project = track["project_map"][assignment["project_id"]]
        timing = _timing(assignment)
        ctx.update(
            assignment=assignment, project=project, timing=timing,
            schedule=build_schedule(timing["start"], timing["due"]),
            sprint=sprint_problems(track, project, progress.lc_status, sprint_quota(assignment["cycle_weeks"])),
            readiness=project_readiness(project, mastery),
            attempts=db.execute("SELECT * FROM submissions WHERE assignment_id = ? ORDER BY id DESC",
                                (assignment["id"],)).fetchall(),
        )
    else:
        recommended, reason = recommend_next(track, progress.passed, progress.last_passed_score, mastery)
        ctx.update(
            recommended=recommended, reason=reason,
            alternatives=[p for p in eligible_projects(track, progress.passed) if p is not recommended],
            readiness=project_readiness(recommended, mastery) if recommended else 0,
        )

    scores = list(progress.passed.values())
    ctx["stats"] = {
        "passed": len(scores),
        "total": len(track["projects"]),
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "lc_solved": sum(1 for s in progress.lc_status.values() if s == "solved"),
        "lc_total": len(track["leetcode"]),
        "extensions": sum(a["extended_count"] for a in progress.history),
    }
    ctx["weakest"] = sorted(track["concepts"], key=lambda c: mastery[c["id"]]["score"])[:4]
    return render_template("cycles/dashboard.html", **ctx)


@bp.route("/roadmap")
@login_required
def roadmap():
    track, progress, mastery = _state(get_db())
    recommended, _ = recommend_next(track, progress.passed, progress.last_passed_score, mastery)
    open_id = progress.open_assignment["project_id"] if progress.open_assignment else None
    groups: dict[int, list[dict]] = {}
    for p in track["projects"]:
        if p["id"] in progress.passed:
            status = "passed"
        elif p["id"] == open_id:
            status = "active"
        elif not locked_reasons(track, p, progress.passed):
            status = "available"
        else:
            status = "locked"
        groups.setdefault(p["level"], []).append({
            "project": p, "status": status, "score": progress.passed.get(p["id"]),
            "missing": locked_reasons(track, p, progress.passed),
            "recommended": bool(recommended and recommended["id"] == p["id"] and not open_id),
            "readiness": project_readiness(p, mastery),
        })
    return render_template("cycles/roadmap.html", track=track, groups=sorted(groups.items()),
                           progress=progress)


@bp.route("/projects/<project_id>")
@login_required
def project_detail(project_id):
    db = get_db()
    track, progress, mastery = _state(db)
    project = track["project_map"].get(project_id)
    if project is None:
        abort(404)

    assignment = progress.open_assignment
    is_active = bool(assignment and assignment["project_id"] == project_id)
    missing = locked_reasons(track, project, progress.passed)
    weeks = assignment["cycle_weeks"] if is_active else g.user["cycle_weeks"]

    if is_active:
        timing = _timing(assignment)
        schedule = build_schedule(timing["start"], timing["due"])
    else:
        timing = None
        now = local_dt(utcnow())
        schedule = build_schedule(now, now + timedelta(weeks=weeks))

    return render_template(
        "cycles/project.html", track=track, project=project, progress=progress, mastery=mastery,
        assignment=assignment if is_active else None, other_open=bool(assignment and not is_active),
        timing=timing, schedule=schedule, weeks=weeks, missing=missing,
        passed_score=progress.passed.get(project_id),
        readiness=project_readiness(project, mastery), ready_threshold=READY_THRESHOLD,
        sprint=sprint_problems(track, project, progress.lc_status, sprint_quota(weeks)),
        concepts=[track["concept_map"][c] for c in project["concepts"]],
        attempts=(db.execute("SELECT * FROM submissions WHERE assignment_id = ? ORDER BY id DESC",
                             (assignment["id"],)).fetchall() if is_active else []),
    )


@bp.route("/projects/<project_id>/start", methods=("POST",))
@login_required
def start_project(project_id):
    db = get_db()
    track, progress, _ = _state(db)
    project = track["project_map"].get(project_id)
    if project is None:
        abort(404)
    if progress.open_assignment:
        flash("Finish or abandon your current project before starting another.", "error")
        return redirect(url_for("cycles.dashboard"))
    if project_id in progress.passed:
        flash("You have already passed that project.", "info")
        return redirect(url_for("cycles.project_detail", project_id=project_id))
    missing = locked_reasons(track, project, progress.passed)
    if missing:
        flash("Pass these first: " + ", ".join(missing), "error")
        return redirect(url_for("cycles.project_detail", project_id=project_id))

    weeks = g.user["cycle_weeks"]
    now = utcnow()
    db.execute(
        "INSERT INTO assignments (user_id, project_id, status, cycle_weeks, started_at, due_at) "
        "VALUES (?, ?, 'active', ?, ?, ?)",
        (g.user["id"], project_id, weeks, to_iso(now), to_iso(now + timedelta(weeks=weeks))),
    )
    db.commit()
    flash(f"Cycle started: {weeks} week{'s' if weeks != 1 else ''} to build and submit.", "success")
    return redirect(url_for("cycles.dashboard"))


@bp.route("/assignments/<int:assignment_id>/extend", methods=("POST",))
@login_required
def extend(assignment_id):
    db = get_db()
    row = _own_open_assignment(db, assignment_id)
    if row is not None:
        new_due = max(from_iso(row["due_at"]), utcnow()) + timedelta(weeks=row["cycle_weeks"])
        db.execute("UPDATE assignments SET due_at = ?, extended_count = extended_count + 1 WHERE id = ?",
                   (to_iso(new_due), assignment_id))
        db.commit()
        flash(f"Deadline extended by {row['cycle_weeks']} week(s). Extensions are tracked on your dashboard.", "info")
    return redirect(url_for("cycles.dashboard"))


@bp.route("/assignments/<int:assignment_id>/abandon", methods=("POST",))
@login_required
def abandon(assignment_id):
    db = get_db()
    row = _own_open_assignment(db, assignment_id)
    if row is not None:
        db.execute("UPDATE assignments SET status = 'abandoned', completed_at = ? WHERE id = ?",
                   (to_iso(utcnow()), assignment_id))
        db.commit()
        flash("Project dropped. Pick another from your roadmap whenever you are ready.", "info")
    return redirect(url_for("cycles.dashboard"))


@bp.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    db = get_db()
    if request.method == "POST":
        error = None
        try:
            weeks = int(request.form.get("cycle_weeks", ""))
        except ValueError:
            weeks, error = None, "Cycle length must be a whole number of weeks."
        else:
            if not MIN_WEEKS <= weeks <= MAX_WEEKS:
                error = f"Cycle length must be between {MIN_WEEKS} and {MAX_WEEKS} weeks."
        track_id = request.form.get("track_id", g.user["track_id"])
        if error is None and track_id not in content.TRACK_IDS:
            error = "Unknown track."
        if error is None and track_id != g.user["track_id"] and load_progress(db, g.user["id"]).open_assignment:
            error = "Finish or drop your current project before switching tracks."
        if error:
            flash(error, "error")
        else:
            db.execute("UPDATE users SET cycle_weeks = ?, track_id = ? WHERE id = ?",
                       (weeks, track_id, g.user["id"]))
            db.commit()
            flash("Settings saved. A new cycle length applies to projects you start from now on.", "success")
            return redirect(url_for("cycles.settings"))
    return render_template("cycles/settings.html", tracks=content.list_tracks(),
                           min_weeks=MIN_WEEKS, max_weeks=MAX_WEEKS)
