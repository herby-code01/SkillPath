"""Concept primers, the LeetCode tracker and industry-style practice questions."""
from __future__ import annotations

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

from . import content
from .auth import login_required
from .db import get_db, to_iso, utcnow
from .progress import MIN_ANSWER_CHARS, load_state
from .security import is_safe_next

bp = Blueprint("learn", __name__)

LC_STATUSES = ("todo", "attempted", "solved")
MAX_ANSWER_CHARS = 4000


def _next(default: str) -> str:
    target = request.form.get("next")
    return target if is_safe_next(target) else default


def _concept_or_404(track: dict, concept_id: str) -> dict:
    concept = track["concept_map"].get(concept_id)
    if concept is None:
        abort(404)
    return concept


@bp.route("/learn")
@login_required
def index():
    track, progress, mastery = load_state(get_db(), g.user)
    used_by = {c["id"]: [p for p in track["projects"] if c["id"] in p["concepts"]] for c in track["concepts"]}
    return render_template("learn/index.html", track=track, mastery=mastery, used_by=used_by)


@bp.route("/learn/<concept_id>")
@login_required
def concept(concept_id):
    track, progress, mastery = load_state(get_db(), g.user)
    concept = _concept_or_404(track, concept_id)
    return render_template(
        "learn/concept.html", track=track, concept=concept, m=mastery[concept_id], progress=progress,
        problems=content.concept_problems(track, concept),
        used_by=[p for p in track["projects"] if concept_id in p["concepts"]],
        min_chars=MIN_ANSWER_CHARS, max_chars=MAX_ANSWER_CHARS,
    )


@bp.route("/learn/<concept_id>/read", methods=("POST",))
@login_required
def mark_read(concept_id):
    track = content.load_track(g.user["track_id"])
    _concept_or_404(track, concept_id)
    db = get_db()
    if request.form.get("read") == "0":
        db.execute("DELETE FROM concept_progress WHERE user_id = ? AND concept_id = ?", (g.user["id"], concept_id))
    else:
        db.execute("INSERT OR IGNORE INTO concept_progress (user_id, concept_id, read_at) VALUES (?, ?, ?)",
                   (g.user["id"], concept_id, to_iso(utcnow())))
    db.commit()
    return redirect(url_for("learn.concept", concept_id=concept_id))


@bp.route("/leetcode")
@login_required
def leetcode():
    track, progress, mastery = load_state(get_db(), g.user)
    wanted_status = request.args.get("status", "all")
    wanted_diff = request.args.get("difficulty", "all")
    used_in: dict[int, list[dict]] = {}
    for c in track["concepts"]:
        for link in c["leetcode"]:
            used_in.setdefault(link["n"], []).append(c)

    rows = []
    for n, info in sorted(track["leetcode"].items()):
        status = progress.lc_status.get(n, "todo")
        if wanted_status in LC_STATUSES and status != wanted_status:
            continue
        if wanted_diff in content.DIFFICULTIES and info["difficulty"] != wanted_diff:
            continue
        rows.append({"n": n, **info, "status": status, "url": content.leetcode_url(info), "concepts": used_in.get(n, [])})

    counts = {s: sum(1 for st in progress.lc_status.values() if st == s) for s in ("solved", "attempted")}
    return render_template("learn/leetcode.html", track=track, rows=rows, counts=counts, total=len(track["leetcode"]),
                           wanted_status=wanted_status, wanted_diff=wanted_diff, statuses=LC_STATUSES,
                           difficulties=content.DIFFICULTIES)


@bp.route("/leetcode/<int:number>/status", methods=("POST",))
@login_required
def set_leetcode_status(number):
    track = content.load_track(g.user["track_id"])
    status = request.form.get("status", "")
    if number not in track["leetcode"] or status not in LC_STATUSES:
        abort(400, description="Unknown problem or status.")
    db = get_db()
    if status == "todo":
        db.execute("DELETE FROM lc_progress WHERE user_id = ? AND problem_no = ?", (g.user["id"], number))
    else:
        db.execute(
            "INSERT INTO lc_progress (user_id, problem_no, status, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, problem_no) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
            (g.user["id"], number, status, to_iso(utcnow())))
    db.commit()
    return redirect(_next(url_for("learn.leetcode")))


@bp.route("/questions/<question_id>/answer", methods=("POST",))
@login_required
def answer_question(question_id):
    track = content.load_track(g.user["track_id"])
    question = track["questions"].get(question_id)
    if question is None:
        abort(404)
    destination = url_for("learn.concept", concept_id=question["concept_id"]) + f"#{question_id}"
    text = request.form.get("answer", "").strip()
    if len(text) < MIN_ANSWER_CHARS:
        flash(f"Write at least {MIN_ANSWER_CHARS} characters. Explaining it in your own words is the point.", "error")
        return redirect(destination)
    db = get_db()
    db.execute(
        "INSERT INTO industry_progress (user_id, question_id, answer, answered_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, question_id) DO UPDATE SET answer = excluded.answer, answered_at = excluded.answered_at",
        (g.user["id"], question_id, text[:MAX_ANSWER_CHARS], to_iso(utcnow())))
    db.commit()
    flash("Answer saved. Compare it with the key points below.", "success")
    return redirect(destination)
