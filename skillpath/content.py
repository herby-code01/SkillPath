"""Load and validate learning tracks from skillpath/tracks/<track_id>/.

Layout of a track directory:
    meta.json          id, name, tagline, description, levels
    leetcode.json      catalog: problem number -> {title, slug, difficulty}
    concepts/*.json    one file per concept (sorted by filename)
    projects/*.json    one file per project (sorted by filename)

To add a new career track, create a new directory with the same layout and add its id
to TRACK_IDS. `validate_track` is run by the test suite against every registered track.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

TRACKS_DIR = Path(__file__).parent / "tracks"
TRACK_IDS = ("ai-ml",)
DEFAULT_TRACK = "ai-ml"
DIFFICULTIES = ("Easy", "Medium", "Hard")
QUESTION_KINDS = ("concept", "coding", "design")
LEETCODE_BASE = "https://leetcode.com/problems/"


def _read_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _track_dir(track_id: str) -> Path:
    if track_id not in TRACK_IDS:
        raise KeyError(f"Unknown track: {track_id!r}")
    return TRACKS_DIR / track_id.replace("-", "_")


@lru_cache(maxsize=None)
def load_track(track_id: str) -> dict:
    root = _track_dir(track_id)
    meta = _read_json(root / "meta.json")
    catalog = {int(k): v for k, v in _read_json(root / "leetcode.json").items()}

    concepts = []
    for path in sorted((root / "concepts").glob("*.json")):
        concept = _read_json(path)
        concept["order"] = len(concepts)
        for i, q in enumerate(concept.get("industry", []), start=1):
            q["id"] = f"{concept['id']}-q{i}"
            q["concept_id"] = concept["id"]
        concepts.append(concept)

    projects = []
    for path in sorted((root / "projects").glob("*.json")):
        project = _read_json(path)
        project["order"] = len(projects)
        projects.append(project)

    track = dict(meta)
    track["leetcode"] = catalog
    track["concepts"] = concepts
    track["concept_map"] = {c["id"]: c for c in concepts}
    track["projects"] = projects
    track["project_map"] = {p["id"]: p for p in projects}
    track["questions"] = {q["id"]: q for c in concepts for q in c.get("industry", [])}
    return track


def list_tracks() -> list[dict]:
    return [load_track(t) for t in TRACK_IDS]


def leetcode_url(problem: dict) -> str:
    return f"{LEETCODE_BASE}{problem['slug']}/"


def concept_problems(track: dict, concept: dict) -> list[dict]:
    """Concept's LeetCode links merged with catalog data, ordered as authored."""
    out = []
    for link in concept.get("leetcode", []):
        info = track["leetcode"][link["n"]]
        out.append({"n": link["n"], "why": link["why"], **info, "url": leetcode_url(info)})
    return out


def project_leetcode_numbers(track: dict, project: dict) -> list[int]:
    seen: list[int] = []
    for cid in project["concepts"]:
        for link in track["concept_map"][cid].get("leetcode", []):
            if link["n"] not in seen:
                seen.append(link["n"])
    return seen


def validate_track(track: dict) -> list[str]:
    """Return a list of human-readable problems; empty means the track is consistent."""
    errors: list[str] = []

    def err(msg: str) -> None:
        errors.append(msg)

    concept_ids = [c["id"] for c in track["concepts"]]
    project_ids = [p["id"] for p in track["projects"]]
    for label, ids in (("concept", concept_ids), ("project", project_ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            err(f"duplicate {label} ids: {sorted(dupes)}")

    for num, info in track["leetcode"].items():
        if info.get("difficulty") not in DIFFICULTIES:
            err(f"leetcode {num}: bad difficulty {info.get('difficulty')!r}")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", info.get("slug", "")):
            err(f"leetcode {num}: bad slug {info.get('slug')!r}")
        if not info.get("title"):
            err(f"leetcode {num}: missing title")

    for c in track["concepts"]:
        cid = c["id"]
        for field in ("title", "why", "explain", "key_points", "leetcode", "industry"):
            if not c.get(field):
                err(f"concept {cid}: missing {field}")
        for link in c.get("leetcode", []):
            if link.get("n") not in track["leetcode"]:
                err(f"concept {cid}: leetcode {link.get('n')} not in catalog")
            if not link.get("why"):
                err(f"concept {cid}: leetcode {link.get('n')} missing 'why'")
        for q in c.get("industry", []):
            if q.get("kind") not in QUESTION_KINDS:
                err(f"concept {cid}: question {q['id']} bad kind {q.get('kind')!r}")
            if not q.get("q") or len(q.get("key_points", [])) < 2:
                err(f"concept {cid}: question {q['id']} needs text and >=2 key_points")

    levels = set(track.get("levels", {}))
    for p in track["projects"]:
        pid = p["id"]
        for field in ("title", "blurb", "brief", "requirements", "deliverables", "concepts", "review"):
            if not p.get(field):
                err(f"project {pid}: missing {field}")
        if str(p.get("level")) not in levels:
            err(f"project {pid}: level {p.get('level')} not defined in meta.levels")
        for cid in p.get("concepts", []):
            if cid not in track["concept_map"]:
                err(f"project {pid}: unknown concept {cid}")
        for req in p.get("requires", []):
            if req not in track["project_map"]:
                err(f"project {pid}: unknown prerequisite {req}")
        checks = p.get("review", {}).get("checks", [])
        if len(checks) < 5:
            err(f"project {pid}: needs at least 5 review checks")
        for chk in checks:
            if not chk.get("label") or not chk.get("any"):
                err(f"project {pid}: check needs label and 'any' patterns: {chk}")
            for pattern in chk.get("any", []):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    err(f"project {pid}: bad regex {pattern!r}: {exc}")

    # prerequisite graph must be acyclic
    state: dict[str, int] = {}

    def visit(pid: str, trail: tuple[str, ...]) -> None:
        if state.get(pid) == 2 or pid not in track["project_map"]:
            return
        if state.get(pid) == 1:
            err(f"prerequisite cycle: {' -> '.join(trail + (pid,))}")
            return
        state[pid] = 1
        for req in track["project_map"][pid].get("requires", []):
            visit(req, trail + (pid,))
        state[pid] = 2

    for pid in project_ids:
        visit(pid, ())

    # every concept should be taught by at least one project, and every project's ordering respects levels
    used = {cid for p in track["projects"] for cid in p.get("concepts", [])}
    for cid in concept_ids:
        if cid not in used:
            err(f"concept {cid} is not used by any project")
    for p in track["projects"]:
        for req in p.get("requires", []):
            req_p = track["project_map"].get(req)
            if req_p and req_p["level"] > p["level"]:
                err(f"project {p['id']} requires higher-level project {req}")
    return errors
