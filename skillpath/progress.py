"""Read a user's learning state from the database in one place."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import content
from .mastery import track_mastery


@dataclass
class Progress:
    read_ids: set[str] = field(default_factory=set)
    lc_status: dict[int, str] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    passed: dict[str, int] = field(default_factory=dict)        # project_id -> best score
    last_passed_score: int | None = None
    open_assignment: object | None = None                        # sqlite3.Row or None
    history: list = field(default_factory=list)                  # all assignments, newest first

    @property
    def answered(self) -> set[str]:
        return {q for q, a in self.answers.items() if len(a.strip()) >= MIN_ANSWER_CHARS}


MIN_ANSWER_CHARS = 20


def load_progress(db, user_id: int) -> Progress:
    p = Progress()
    p.read_ids = {r["concept_id"] for r in db.execute(
        "SELECT concept_id FROM concept_progress WHERE user_id = ?", (user_id,))}
    p.lc_status = {r["problem_no"]: r["status"] for r in db.execute(
        "SELECT problem_no, status FROM lc_progress WHERE user_id = ?", (user_id,))}
    p.answers = {r["question_id"]: r["answer"] for r in db.execute(
        "SELECT question_id, answer FROM industry_progress WHERE user_id = ?", (user_id,))}
    p.history = db.execute(
        "SELECT * FROM assignments WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    for a in reversed(p.history):  # oldest first so the final value is the latest pass
        if a["status"] == "passed":
            p.passed[a["project_id"]] = a["best_score"] or 0
            p.last_passed_score = a["best_score"]
    p.open_assignment = next((a for a in p.history if a["status"] in ("active", "needs_revision")), None)
    return p


def load_state(db, user):
    """Return (track, progress, mastery) for a user row."""
    track = content.load_track(user["track_id"])
    progress = load_progress(db, user["id"])
    mastery = track_mastery(track, read_ids=progress.read_ids, lc_status=progress.lc_status,
                            answered=progress.answered, passed_project_ids=progress.passed)
    return track, progress, mastery
