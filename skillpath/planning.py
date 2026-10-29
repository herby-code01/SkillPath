"""Cycle planning: the day-by-day schedule and the LeetCode sprint for a project."""
from __future__ import annotations

from datetime import datetime, timedelta

from .content import concept_problems

DIFFICULTY_RANK = {"Easy": 0, "Medium": 1, "Hard": 2}
PROBLEMS_PER_WEEK = 2

# (name, share of the cycle, what to do)
PHASES = (
    ("Learn", 0.25, "Read the concept primers, then solve the warm-up LeetCode problems that match them."),
    ("Build", 0.55, "Implement the project requirements. Commit small and often; get something end-to-end working early."),
    ("Polish", 0.15, "Add tests, docs and a README, clean up the code and run the project from a fresh checkout."),
    ("Submit", 0.05, "Zip the project (or upload a single .py/.ipynb), submit it and read the review."),
)


def build_schedule(start: datetime, due: datetime) -> list[dict]:
    """Split [start, due] into the four phases. Always at least one day per phase."""
    total = max((due.date() - start.date()).days, len(PHASES))
    cuts, acc = [], 0.0
    for _name, share, _ in PHASES[:-1]:
        acc += share
        cuts.append(round(total * acc))
    # enforce strictly increasing, at least one day each, leaving the final day for Submit
    fixed, prev = [], 0
    for i, cut in enumerate(cuts):
        cut = max(cut, prev + 1)
        cut = min(cut, total - (len(PHASES) - 1 - i))
        fixed.append(cut)
        prev = cut
    bounds = [0, *fixed, total]
    out = []
    for i, (name, _share, focus) in enumerate(PHASES):
        first = start.date() + timedelta(days=bounds[i])
        last = start.date() + timedelta(days=bounds[i + 1] - (1 if i < len(PHASES) - 1 else 0))
        out.append({"name": name, "start": first, "end": max(first, last), "focus": focus})
    return out


def sprint_quota(cycle_weeks: int) -> int:
    return max(2, PROBLEMS_PER_WEEK * cycle_weeks)


def sprint_problems(track: dict, project: dict, lc_status: dict[int, str], quota: int) -> list[dict]:
    """Pick up to `quota` unsolved problems, round-robin across the project's concepts, easiest first."""
    queues = []
    for cid in project["concepts"]:
        problems = [p for p in concept_problems(track, track["concept_map"][cid])
                    if lc_status.get(p["n"]) != "solved"]
        problems.sort(key=lambda p: DIFFICULTY_RANK[p["difficulty"]])  # stable: keeps authored order
        queues.append([{**p, "concept_id": cid} for p in problems])

    chosen: list[dict] = []
    seen: set[int] = set()
    while len(chosen) < quota and any(queues):
        for queue in queues:
            while queue and queue[0]["n"] in seen:
                queue.pop(0)
            if queue and len(chosen) < quota:
                item = queue.pop(0)
                seen.add(item["n"])
                chosen.append(item)
    return chosen
