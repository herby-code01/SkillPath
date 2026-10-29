"""Static reviewer. Scores a submission WITHOUT ever executing it.

Accepted uploads: a .zip project, a single .py file, or a .ipynb notebook.

Score (100 points, categories that do not apply are left out and the rest is rescaled):
    Requirements  45  each project check looks for matching names (functions, classes,
                      variables, attributes, imports) found by parsing the code with `ast`.
                      Comments and strings never count, so keywords cannot be pasted in.
    Code quality  20  syntax 5, docstrings 4, function size 4, code hygiene 4,
                      reproducibility 3 (only for projects that involve randomness)
    Tests         15  test files, number of tests, assertions     (zip only)
    Docs          10  README present, substantial, with run/usage/results info  (zip only)
    Packaging     10  dependency file, .gitignore, no committed secrets          (zip only)

Adjustments: -5 when submitted after the deadline; single-file uploads are capped at 85.
Gates (a pass is impossible while any is open): all files must parse, no hard-coded secrets,
and at least 60% of the project's requirement checks must be found.

Limits, stated plainly: this checks structure and engineering habits, not whether the
algorithm is *correct*. Passing means the project is built the way the brief describes.
"""
from __future__ import annotations

import ast
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

MAX_ARCHIVE_FILES = 800
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = (".zip", ".py", ".ipynb")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".idea", ".vscode",
             ".pytest_cache", "site-packages", "dist", "build", ".ipynb_checkpoints", ".mypy_cache"}
TEXT_EXTS = {".py", ".md", ".txt", ".rst", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".json",
             ".csv", ".sh", ".env", ".ipynb", ".dockerfile", ".html", ".js"}
TEXT_NAMES = {"dockerfile", "makefile", ".gitignore", ".env", "readme", "license", "procfile"}
DEP_FILES = {"requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml",
             "pipfile", "setup.py", "setup.cfg", "package.json", "poetry.lock"}

MIN_LINES_PER_CHECK = 6
MAX_FUNCTION_LINES = 60
LATE_PENALTY = 5
SINGLE_FILE_CAP = 85
COVERAGE_GATE = 0.6

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)\b"
               r"\s*[:=]\s*['\"][A-Za-z0-9_\-+/=.]{16,}['\"]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
SEED_CALLS = {"seed", "manual_seed", "default_rng", "randomstate"}
SEED_KEYWORDS = {"random_state", "seed", "random_seed"}


class SubmissionError(ValueError):
    """The upload cannot be reviewed (bad type, unsafe or oversized archive, unreadable file)."""


# --------------------------------------------------------------------------- loading
def _is_text_path(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in TEXT_EXTS or p.name.lower() in TEXT_NAMES


def _notebook_to_source(raw: str) -> str:
    try:
        nb = json.loads(raw)
        cells = nb["cells"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SubmissionError("That notebook could not be read as JSON.") from exc
    chunks = []
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        lines = [("pass  # notebook magic" if ln.lstrip().startswith(("%", "!")) else ln)
                 for ln in src.splitlines()]
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n"


def _decode(blob: bytes) -> str:
    return blob.decode("utf-8", errors="replace")


def load_submission(filename: str, data: bytes) -> dict:
    """Return {'files': {path: text}, 'names': [every path], 'is_project': bool, 'skipped': [...]}."""
    name = filename.lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        raise SubmissionError("Upload a .zip project, a .py file or a .ipynb notebook.")
    if not data:
        raise SubmissionError("That file is empty.")

    if name.endswith(".py"):
        return {"files": {filename: _decode(data)}, "names": [filename], "is_project": False, "skipped": []}
    if name.endswith(".ipynb"):
        virtual = filename[:-6] + ".py"
        return {"files": {virtual: _notebook_to_source(_decode(data))}, "names": [filename],
                "is_project": False, "skipped": []}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SubmissionError("That is not a valid zip file.") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ARCHIVE_FILES:
            raise SubmissionError(f"The archive has too many files (limit {MAX_ARCHIVE_FILES}). "
                                  "Remove datasets, virtual environments and build output.")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise SubmissionError("The archive expands to more than 25 MB. Remove datasets and model files.")
        if any(i.flag_bits & 0x1 for i in infos):
            raise SubmissionError("Encrypted zip files cannot be reviewed.")

        files: dict[str, str] = {}
        names: list[str] = []
        skipped: list[str] = []
        for info in infos:
            raw_name = info.filename.replace("\\", "/")
            parts = PurePosixPath(raw_name).parts
            if raw_name.startswith("/") or ".." in parts:
                skipped.append(raw_name)  # never trust unsafe paths; nothing is extracted to disk anyway
                continue
            if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in parts[:-1]) or parts[-1] == ".DS_Store":
                continue
            names.append(raw_name)
            if _is_text_path(raw_name):
                with zf.open(info) as member:
                    blob = member.read(MAX_FILE_BYTES + 1)
                if len(blob) > MAX_FILE_BYTES:
                    skipped.append(raw_name)
                    continue
                text = _decode(blob)
                if raw_name.lower().endswith(".ipynb"):
                    try:
                        files[raw_name[:-6] + ".py"] = _notebook_to_source(text)
                    except SubmissionError:
                        skipped.append(raw_name)
                    continue
                files[raw_name] = text

    if not names:
        raise SubmissionError("The archive has no reviewable files.")
    # drop one shared top-level folder (the usual "myproject/" wrapper) so paths read naturally
    tops = {PurePosixPath(n).parts[0] for n in names if len(PurePosixPath(n).parts) > 1}
    single_root = len(tops) == 1 and all(len(PurePosixPath(n).parts) > 1 for n in names)
    if single_root:
        strip = lambda n: "/".join(PurePosixPath(n).parts[1:])  # noqa: E731
        files = {strip(k): v for k, v in files.items()}
        names = [strip(n) for n in names]
    return {"files": files, "names": names, "is_project": True, "skipped": skipped}


# --------------------------------------------------------------------------- analysis
def _is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    base = p.name.lower()
    return (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
            or any(part.lower() in ("tests", "test") for part in p.parts[:-1]))


class _Facts:
    def __init__(self) -> None:
        self.impl_idents: set[str] = set()
        self.test_idents: set[str] = set()
        self.parse_errors: list[str] = []
        self.py_files = 0
        self.code_lines = 0
        self.public_defs = 0
        self.documented = 0
        self.long_funcs: list[str] = []
        self.func_count = 0
        self.bare_excepts = 0
        self.star_imports = 0
        self.dangerous_calls = 0
        self.seeded = False
        self.test_files = 0
        self.test_funcs = 0
        self.asserts = 0


def _count_code_lines(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))


def _collect(tree: ast.AST, path: str, is_test: bool, facts: _Facts) -> None:
    idents = facts.test_idents if is_test else facts.impl_idents
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            idents.add(node.name.lower())
            if not is_test and not node.name.startswith("_"):
                facts.public_defs += 1
                facts.documented += 1 if ast.get_docstring(node) else 0
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if is_test and node.name.startswith("test"):
                    facts.test_funcs += 1
                if not is_test:
                    facts.func_count += 1
                    length = (node.end_lineno or node.lineno) - node.lineno + 1
                    if length > MAX_FUNCTION_LINES:
                        facts.long_funcs.append(f"{path}:{node.name} ({length} lines)")
                for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                    idents.add(a.arg.lower())
                for a in (node.args.vararg, node.args.kwarg):
                    if a:
                        idents.add(a.arg.lower())
        elif isinstance(node, ast.Name):
            idents.add(node.id.lower())
            if node.id in ("eval", "exec") and isinstance(node.ctx, ast.Load):
                facts.dangerous_calls += 1
        elif isinstance(node, ast.Attribute):
            idents.add(node.attr.lower())
        elif isinstance(node, ast.keyword) and node.arg:
            idents.add(node.arg.lower())
            if node.arg.lower() in SEED_KEYWORDS:
                facts.seeded = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                idents.update(part.lower() for part in alias.name.split("."))
                if alias.asname:
                    idents.add(alias.asname.lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                idents.update(part.lower() for part in node.module.split("."))
            for alias in node.names:
                if alias.name == "*":
                    facts.star_imports += 1
                idents.add(alias.name.lower())
                if alias.asname:
                    idents.add(alias.asname.lower())
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            facts.bare_excepts += 1
        elif isinstance(node, ast.Assert) and is_test:
            facts.asserts += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")).lower()
            if fname in SEED_CALLS and (node.args or node.keywords):
                facts.seeded = True
            if is_test and fname.startswith("assert"):
                facts.asserts += 1


def analyze(files: dict[str, str]) -> _Facts:
    facts = _Facts()
    for path, text in files.items():
        if not path.lower().endswith(".py"):
            continue
        facts.py_files += 1
        is_test = _is_test_path(path)
        if is_test:
            facts.test_files += 1
        else:
            facts.code_lines += _count_code_lines(text)
        try:
            tree = ast.parse(text, filename=path)
        except (SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", None)
            facts.parse_errors.append(f"{path}" + (f" line {line}" if line else ""))
            continue
        _collect(tree, path, is_test, facts)
    return facts


def find_secrets(files: dict[str, str], names: list[str]) -> list[str]:
    """Locations only; the matched text is never copied into a report."""
    hits = []
    for name in names:
        if PurePosixPath(name).name.lower() in (".env",) or PurePosixPath(name).suffix.lower() == ".env":
            hits.append(f"{name} (environment file committed)")
    for path, text in files.items():
        if path.lower().endswith((".md", ".rst")):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in SECRET_PATTERNS):
                hits.append(f"{path} line {lineno}")
                break
    return hits


# --------------------------------------------------------------------------- scoring
def _hint(patterns: list[str]) -> str:
    cleaned = []
    for p in patterns:
        word = re.sub(r"[\^$]", "", p).replace("\\", "")
        if word and word not in cleaned:
            cleaned.append(word)
    return ", ".join(cleaned[:4])


def _finding(label: str, status: str, earned: float, maximum: float, detail: str = "", fix: str = "") -> dict:
    return {"label": label, "status": status, "earned": round(earned, 2), "max": round(maximum, 2),
            "detail": detail, "fix": fix}


def _requirement_findings(project: dict, facts: _Facts, names: list[str]) -> tuple[list[dict], float]:
    checks = project["review"]["checks"]
    each = 45 / len(checks)
    substance = min(1.0, facts.code_lines / (MIN_LINES_PER_CHECK * len(checks)))
    basenames = [PurePosixPath(n).name.lower() for n in names]
    findings, matched = [], 0
    for chk in checks:
        patterns = [re.compile(p) for p in chk["any"]]
        if chk.get("files"):
            pool = set(basenames)
        elif chk.get("scope") == "tests":
            pool = facts.test_idents
        else:
            pool = facts.impl_idents
        found = any(p.search(item) for p in patterns for item in pool)
        if found:
            matched += 1
            earned = each * substance
            note = "" if substance >= 1 else "Credit reduced: the submission has very little code."
            findings.append(_finding(chk["label"], "pass", earned, each, note))
        else:
            where = "a file named like" if chk.get("files") else "code using names like"
            findings.append(_finding(
                chk["label"], "fail", 0, each, "Not found in your submission.",
                f"Implement '{chk['label']}' ({where}: {_hint(chk['any'])}) and keep it in your source files."))
    return findings, matched / len(checks)


def _quality_findings(project: dict, facts: _Facts) -> list[dict]:
    out = []
    if facts.py_files == 0:
        out.append(_finding("Python source", "fail", 0, 5, "No .py files (or notebook code cells) were found.",
                            "Submit your source code as .py files or a notebook."))
        return out
    ok = facts.py_files - len(facts.parse_errors)
    if facts.parse_errors:
        out.append(_finding("Code parses", "fail", 5 * ok / facts.py_files, 5,
                            "Syntax errors in: " + ", ".join(facts.parse_errors[:5]),
                            "Fix the syntax errors; the reviewer cannot read those files."))
    else:
        out.append(_finding("Code parses", "pass", 5, 5, f"{facts.py_files} Python file(s) parsed cleanly."))

    if facts.public_defs:
        ratio = facts.documented / facts.public_defs
        earned = 4 * min(1.0, ratio / 0.5)
        out.append(_finding("Docstrings", "pass" if ratio >= 0.5 else "warn", earned, 4,
                            f"{facts.documented} of {facts.public_defs} public functions/classes documented.",
                            "" if ratio >= 0.5 else "Add one-line docstrings to at least half of your public functions and classes."))
    else:
        out.append(_finding("Docstrings", "fail", 0, 4, "No functions or classes found.",
                            "Organize the code into documented functions or classes."))

    if facts.func_count == 0:
        out.append(_finding("Function size", "fail", 0, 4, "No functions found.",
                            "Break the work into small functions instead of one long script."))
    elif facts.long_funcs:
        share = 1 - len(facts.long_funcs) / facts.func_count
        out.append(_finding("Function size", "warn", 4 * max(0.0, share), 4,
                            f"Long functions (over {MAX_FUNCTION_LINES} lines): " + ", ".join(facts.long_funcs[:4]),
                            "Split long functions into smaller, testable pieces."))
    else:
        out.append(_finding("Function size", "pass", 4, 4, f"All {facts.func_count} functions are under {MAX_FUNCTION_LINES} lines."))

    problems = []
    if facts.bare_excepts:
        problems.append(f"{facts.bare_excepts} bare 'except:'")
    if facts.star_imports:
        problems.append(f"{facts.star_imports} wildcard import(s)")
    if facts.dangerous_calls:
        problems.append("use of eval/exec")
    if problems:
        out.append(_finding("Code hygiene", "warn", max(0, 4 - len(problems)), 4, "Found: " + ", ".join(problems),
                            "Catch specific exceptions, import names explicitly, and avoid eval/exec."))
    else:
        out.append(_finding("Code hygiene", "pass", 4, 4, "No bare excepts, wildcard imports or eval/exec."))

    if project["review"].get("seed"):
        if facts.seeded:
            out.append(_finding("Reproducibility", "pass", 3, 3, "A random seed is set."))
        else:
            out.append(_finding("Reproducibility", "fail", 0, 3, "No random seed found.",
                                "Set a seed (np.random.default_rng(42), random_state=42) so results can be reproduced."))
    return out


def _test_findings(facts: _Facts) -> list[dict]:
    out = []
    if facts.test_files:
        out.append(_finding("Test files", "pass", 5, 5, f"{facts.test_files} test file(s)."))
    else:
        out.append(_finding("Test files", "fail", 0, 5, "No test files found.",
                            "Add a tests/ folder with test_*.py files."))
    out.append(_finding("Number of tests", "pass" if facts.test_funcs >= 5 else "warn" if facts.test_funcs else "fail",
                        5 * min(1.0, facts.test_funcs / 5), 5, f"{facts.test_funcs} test function(s).",
                        "" if facts.test_funcs >= 5 else "Aim for at least 5 focused tests."))
    needed = max(1, facts.test_funcs)
    ratio = min(1.0, facts.asserts / needed) if facts.test_funcs else 0.0
    out.append(_finding("Assertions", "pass" if ratio >= 1 else "warn" if ratio else "fail", 5 * ratio, 5,
                        f"{facts.asserts} assertion(s) across {facts.test_funcs} test(s).",
                        "" if ratio >= 1 else "Every test should assert something specific."))
    return out


def _doc_findings(files: dict[str, str], names: list[str]) -> list[dict]:
    readme_key = next((n for n in names if PurePosixPath(n).name.lower().startswith("readme")
                       and "/" not in n), None) or next(
        (n for n in names if PurePosixPath(n).name.lower().startswith("readme")), None)
    if not readme_key or readme_key not in files:
        return [_finding("README", "fail", 0, 10, "No README found.",
                         "Add a README.md describing what the project does, how to run it and what results you got.")]
    text = files[readme_key]
    words = len(re.findall(r"\w+", text))
    headings = len(re.findall(r"(?m)^#{1,6}\s+\S", text))
    low = text.lower()
    topics = sum(1 for pat in (r"install|setup|requirements", r"usage|run|example|how to", r"result|accuracy|score|metric|finding",
                               r"test") if re.search(pat, low))
    return [
        _finding("README present", "pass", 3, 3, f"Found {readme_key}."),
        _finding("README substance", "pass" if words >= 150 else "warn", 4 * min(1.0, words / 150), 4,
                 f"{words} words.", "" if words >= 150 else "Expand the README to at least ~150 words."),
        _finding("README covers run/usage/results", "pass" if topics >= 3 else "warn", 3 * min(1.0, topics / 3), 3,
                 f"{headings} heading(s); covers {topics} of 4 topics (setup, usage, results, tests).",
                 "" if topics >= 3 else "Add sections for setup, usage, results and how to run the tests."),
    ]


def _packaging_findings(files: dict[str, str], names: list[str], secrets: list[str]) -> list[dict]:
    base = {PurePosixPath(n).name.lower() for n in names}
    out = []
    dep = sorted(base & DEP_FILES)
    out.append(_finding("Dependency file", "pass" if dep else "fail", 4 if dep else 0, 4,
                        f"Found {dep[0]}." if dep else "No requirements.txt or pyproject.toml.",
                        "" if dep else "List your dependencies in requirements.txt so others can run the project."))
    has_ignore = ".gitignore" in base
    out.append(_finding(".gitignore", "pass" if has_ignore else "warn", 3 if has_ignore else 0, 3,
                        "Found." if has_ignore else "No .gitignore.",
                        "" if has_ignore else "Add a .gitignore (virtualenvs, __pycache__, data, model files)."))
    if secrets:
        out.append(_finding("No committed secrets", "fail", 0, 3, "Possible secret in: " + ", ".join(secrets[:4]),
                            "Remove the key, rotate it (treat it as leaked) and load secrets from environment variables."))
    else:
        out.append(_finding("No committed secrets", "pass", 3, 3, "No keys, tokens or .env files detected."))
    return out


def review_submission(project: dict, submission: dict, *, late: bool = False, pass_score: int = 70) -> dict:
    """Score a loaded submission against a project definition and return the full report."""
    files, names, is_project = submission["files"], submission["names"], submission["is_project"]
    facts = analyze(files)
    secrets = find_secrets(files, names)

    req_findings, coverage = _requirement_findings(project, facts, names)
    categories = [
        {"name": "Requirements", "findings": req_findings},
        {"name": "Code quality", "findings": _quality_findings(project, facts)},
    ]
    if is_project:
        categories += [
            {"name": "Tests", "findings": _test_findings(facts)},
            {"name": "Documentation", "findings": _doc_findings(files, names)},
            {"name": "Packaging", "findings": _packaging_findings(files, names, secrets)},
        ]
    for cat in categories:
        cat["earned"] = round(sum(f["earned"] for f in cat["findings"]), 1)
        cat["max"] = round(sum(f["max"] for f in cat["findings"]), 1)

    earned = sum(c["earned"] for c in categories)
    possible = sum(c["max"] for c in categories) or 1
    score = earned / possible * 100
    adjustments = []
    if late:
        score -= LATE_PENALTY
        adjustments.append(f"-{LATE_PENALTY}: submitted after the deadline (extend a cycle before it ends to avoid this).")
    if not is_project and score > SINGLE_FILE_CAP:
        score = SINGLE_FILE_CAP
        adjustments.append(f"Capped at {SINGLE_FILE_CAP}: single-file uploads are not scored on tests, docs or packaging. "
                           "Upload a zip to earn a higher score.")
    score = int(max(0, min(100, round(score))))

    gates = []
    if facts.parse_errors:
        gates.append("Some files have syntax errors: " + ", ".join(facts.parse_errors[:4]))
    if secrets:
        gates.append("A possible hard-coded secret was found. Remove it before this can pass.")
    if facts.py_files == 0:
        gates.append("No Python source was found.")
    if coverage < COVERAGE_GATE:
        gates.append(f"Only {round(coverage * 100)}% of the project's requirements were found (need {round(COVERAGE_GATE * 100)}%).")
    passed = score >= pass_score and not gates

    lost = sorted((f for c in categories for f in c["findings"] if f["fix"]),
                  key=lambda f: f["max"] - f["earned"], reverse=True)
    return {
        "score": score,
        "passed": passed,
        "pass_score": pass_score,
        "late": late,
        "is_project": is_project,
        "coverage": round(coverage * 100),
        "gates": gates,
        "adjustments": adjustments,
        "categories": categories,
        "next_steps": [f"{f['label']}: {f['fix']}" for f in lost[:5]],
        "stats": {"files": len(names), "python_files": facts.py_files, "code_lines": facts.code_lines,
                  "tests": facts.test_funcs, "skipped": submission.get("skipped", [])},
    }
