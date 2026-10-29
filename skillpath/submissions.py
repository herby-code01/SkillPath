"""Submit a project for review and read the scored report."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   url_for)
from werkzeug.utils import secure_filename

from . import content
from .auth import login_required
from .db import from_iso, get_db, to_iso, utcnow
from .mastery import track_mastery
from .progress import load_progress
from .recommender import recommend_next
from .reviewer import ALLOWED_EXTENSIONS, SubmissionError, load_submission, review_submission

bp = Blueprint("submissions", __name__)


def _store_upload(user_id: int, assignment_id: int, filename: str, data: bytes) -> str:
    """Keep a copy of the upload under instance/uploads/<user>/ (never served back to anyone)."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".bin"
    folder = Path(current_app.config["UPLOAD_DIR"]) / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{assignment_id}-{uuid.uuid4().hex[:12]}{ext}"
    (folder / name).write_bytes(data)
    return f"{user_id}/{name}"


@bp.route("/assignments/<int:assignment_id>/submit", methods=("POST",))
@login_required
def submit(assignment_id):
    db = get_db()
    assignment = db.execute("SELECT * FROM assignments WHERE id = ? AND user_id = ?",
                            (assignment_id, g.user["id"])).fetchone()
    if assignment is None:
        abort(404)
    back = redirect(url_for("cycles.project_detail", project_id=assignment["project_id"]))
    if assignment["status"] not in ("active", "needs_revision"):
        flash("That project cycle is already closed.", "error")
        return redirect(url_for("cycles.dashboard"))

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Choose a .zip, .py or .ipynb file to submit.", "error")
        return back
    data = upload.read()
    filename = secure_filename(upload.filename) or "upload"
    try:
        submission = load_submission(filename, data)
    except SubmissionError as exc:
        flash(str(exc), "error")
        return back

    track = content.load_track(g.user["track_id"])
    project = track["project_map"][assignment["project_id"]]
    now = utcnow()
    late = now > from_iso(assignment["due_at"])
    report = review_submission(project, submission, late=late,
                               pass_score=current_app.config["PASS_SCORE"])

    cur = db.execute(
        "INSERT INTO submissions (assignment_id, user_id, filename, stored_path, submitted_at, late, "
        "score, passed, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, g.user["id"], filename,
         _store_upload(g.user["id"], assignment_id, filename, data), to_iso(now), int(late),
         report["score"], int(report["passed"]), json.dumps(report)),
    )
    if report["passed"]:
        db.execute("UPDATE assignments SET status = 'passed', completed_at = ?, best_score = ? WHERE id = ?",
                   (to_iso(now), report["score"], assignment_id))
        flash(f"Passed with {report['score']}/100. Your next project is ready on the dashboard.", "success")
    else:
        best = max(assignment["best_score"] or 0, report["score"])
        db.execute("UPDATE assignments SET status = 'needs_revision', best_score = ? WHERE id = ?",
                   (best, assignment_id))
        flash(f"Scored {report['score']}/100. Not a pass yet: fix the items below and resubmit.", "info")
    db.commit()
    return redirect(url_for("submissions.report", submission_id=cur.lastrowid))


@bp.route("/submissions/<int:submission_id>")
@login_required
def report(submission_id):
    db = get_db()
    row = db.execute("SELECT * FROM submissions WHERE id = ? AND user_id = ?",
                     (submission_id, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    assignment = db.execute("SELECT * FROM assignments WHERE id = ?", (row["assignment_id"],)).fetchone()
    track = content.load_track(g.user["track_id"])
    project = track["project_map"].get(assignment["project_id"])

    next_project = reason = None
    if row["passed"]:
        progress = load_progress(db, g.user["id"])
        mastery = track_mastery(track, read_ids=progress.read_ids, lc_status=progress.lc_status,
                                answered=progress.answered, passed_project_ids=progress.passed)
        next_project, reason = recommend_next(track, progress.passed, row["score"], mastery)
    return render_template("submissions/report.html", submission=row, assignment=assignment,
                           project=project, report=json.loads(row["report_json"]),
                           next_project=next_project, reason=reason, track=track)
