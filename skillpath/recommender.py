"""Pick the next project for a user.

Rules, in order:
1. Eligible = not yet passed and every prerequisite project already passed.
2. Pick a difficulty level from the last passing score:
     >= 90   step up: the hardest eligible project that is at most one level above anything passed
     else    the easiest eligible project
3. Among eligible projects at that level, prefer the one whose concepts the user has
   practiced least (so each cycle targets weak spots), then fall back to authored order.
"""
from __future__ import annotations

STEP_UP_SCORE = 90


def eligible_projects(track: dict, passed: dict[str, int]) -> list[dict]:
    out = [p for p in track["projects"]
           if p["id"] not in passed and all(r in passed for r in p.get("requires", []))]
    return sorted(out, key=lambda p: (p["level"], p["order"]))


def locked_reasons(track: dict, project: dict, passed: dict[str, int]) -> list[str]:
    """Titles of prerequisite projects that still need to be passed."""
    return [track["project_map"][r]["title"] for r in project.get("requires", []) if r not in passed]


def _weakness(project: dict, mastery: dict[str, dict] | None) -> float:
    """0-100: how little the user has practiced this project's concepts (higher = weaker)."""
    if not mastery:
        return 0.0
    scores = [mastery[c]["score"] for c in project["concepts"] if c in mastery]
    return 100 - (sum(scores) / len(scores)) if scores else 0.0


def recommend_next(track: dict, passed: dict[str, int], last_score: int | None = None,
                   mastery: dict[str, dict] | None = None) -> tuple[dict | None, str]:
    """Return (project, reason). project is None when the whole track is finished."""
    candidates = eligible_projects(track, passed)
    if not candidates:
        return None, "You have passed every project in this track."

    easiest = candidates[0]["level"]
    max_passed = max((track["project_map"][pid]["level"] for pid in passed
                      if pid in track["project_map"]), default=0)

    if last_score is None:
        level, reason = easiest, "Start at the beginning of the path."
    elif last_score >= STEP_UP_SCORE:
        reachable = [p for p in candidates if p["level"] <= max_passed + 1]
        level = max(p["level"] for p in reachable) if reachable else easiest
        if level > easiest:
            reason = f"You scored {last_score} on your last project, so we are stepping up the difficulty."
        else:
            reason = f"You scored {last_score} on your last project; this is the best next step on the path."
    else:
        level, reason = easiest, f"You passed with {last_score}. Continuing along the path."

    pool = [p for p in candidates if p["level"] == level] or candidates
    best = max(pool, key=lambda p: (_weakness(p, mastery), -p["order"]))
    if len(pool) > 1 and _weakness(best, mastery) > 0 and best is not pool[0]:
        reason += " Picked because it covers the concepts you have practiced least."
    return best, reason
