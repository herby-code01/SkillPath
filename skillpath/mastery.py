"""Concept mastery: how well a user knows a concept, from four kinds of evidence.

    read      15%  marked the primer as read
    leetcode  40%  linked LeetCode problems (solved = full credit, attempted = partial)
    industry  25%  industry-style questions answered in writing
    applied   20%  the concept was used in a project that passed review

`learning_score` is the same calculation without the applied part (rescaled to 0-100). It
measures readiness *before* a project, so it is what gates the "are you ready to start" hint.
"""
from __future__ import annotations

WEIGHTS = {"read": 0.15, "leetcode": 0.40, "industry": 0.25, "applied": 0.20}
LC_CREDIT = {"solved": 1.0, "attempted": 0.3, "todo": 0.0}
READY_THRESHOLD = 50  # learning_score at which we call a user ready to start a project


def concept_mastery(concept: dict, *, read: bool, lc_status: dict[int, str],
                    answered: set[str], applied: bool) -> dict:
    problems = [link["n"] for link in concept.get("leetcode", [])]
    questions = [q["id"] for q in concept.get("industry", [])]

    lc_part = (sum(LC_CREDIT.get(lc_status.get(n, "todo"), 0.0) for n in problems) / len(problems)
               if problems else 0.0)
    ind_part = (sum(1 for q in questions if q in answered) / len(questions)) if questions else 0.0
    parts = {
        "read": 1.0 if read else 0.0,
        "leetcode": lc_part,
        "industry": ind_part,
        "applied": 1.0 if applied else 0.0,
    }
    score = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()))
    learn_weight = 1.0 - WEIGHTS["applied"]
    learning = round(100 * sum(WEIGHTS[k] * parts[k] for k in ("read", "leetcode", "industry")) / learn_weight)
    return {
        "score": score,
        "learning_score": learning,
        "parts": parts,
        "solved": sum(1 for n in problems if lc_status.get(n) == "solved"),
        "problems": len(problems),
        "answered": sum(1 for q in questions if q in answered),
        "questions": len(questions),
        "read": read,
        "applied": applied,
    }


def applied_concepts(track: dict, passed_project_ids) -> set[str]:
    out: set[str] = set()
    for pid in passed_project_ids:
        project = track["project_map"].get(pid)
        if project:
            out.update(project["concepts"])
    return out


def track_mastery(track: dict, *, read_ids: set[str], lc_status: dict[int, str],
                  answered: set[str], passed_project_ids) -> dict[str, dict]:
    applied = applied_concepts(track, passed_project_ids)
    return {
        c["id"]: concept_mastery(c, read=c["id"] in read_ids, lc_status=lc_status,
                                 answered=answered, applied=c["id"] in applied)
        for c in track["concepts"]
    }


def project_readiness(project: dict, mastery: dict[str, dict]) -> int:
    """Average learning score of the concepts a project needs (0-100)."""
    scores = [mastery[cid]["learning_score"] for cid in project["concepts"] if cid in mastery]
    return round(sum(scores) / len(scores)) if scores else 0
