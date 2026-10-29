import io
import json
import unittest
import zipfile

from skillpath import content, reviewer
from skillpath.reviewer import SubmissionError, load_submission, review_submission

from .helpers import make_zip

TRACK = content.load_track("ai-ml")
EXPLORER = TRACK["project_map"]["data-explorer"]

GOOD_SOURCE = '''"""CSV profiler."""
import argparse
import csv


def load(path):
    """Load a CSV file into a list of dict rows."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def missing_report(rows):
    """Count missing values per column."""
    counts = {}
    for row in rows:
        for key, value in row.items():
            if value in ("", None):
                counts[key] = counts.get(key, 0) + 1
    return counts


def summary_stats(values):
    """Return mean and std for a list of numbers."""
    n = len(values)
    mean = sum(values) / n
    std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
    return {"mean": mean, "std": std}


def correlation(xs, ys):
    """Pearson correlation between two numeric lists."""
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den if den else 0.0


def find_duplicates(rows):
    """Return rows that appear more than once."""
    seen, dupes = set(), []
    for row in rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            dupes.append(row)
        seen.add(key)
    return dupes


def clean(rows):
    """Drop duplicate rows and fill blanks with a placeholder."""
    dupes = find_duplicates(rows)
    kept = [r for r in rows if r not in dupes]
    return [{k: (v if v != "" else "unknown") for k, v in r.items()} for r in kept]


def column_types(rows):
    """Infer 'number' or 'text' for every column."""
    types = {}
    for key in rows[0]:
        try:
            [float(r[key]) for r in rows if r[key] != ""]
            types[key] = "number"
        except ValueError:
            types[key] = "text"
    return types


def quartiles(values):
    """Return the 25th, 50th and 75th percentiles of a list of numbers."""
    ordered = sorted(values)

    def pick(q):
        index = q * (len(ordered) - 1)
        low, high = int(index), min(int(index) + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)

    return pick(0.25), pick(0.5), pick(0.75)


def iqr_outliers(values):
    """Values outside 1.5 IQR of the quartiles."""
    q1, _, q3 = quartiles(values)
    spread = q3 - q1
    return [v for v in values if v < q1 - 1.5 * spread or v > q3 + 1.5 * spread]


def to_markdown(report):
    """Render a dict report as a markdown table."""
    lines = ["| column | value |", "| --- | --- |"]
    for key, value in report.items():
        lines.append(f"| {key} | {value} |")
    return "\\n".join(lines)


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    rows = load(args.path)
    print(missing_report(rows))


if __name__ == "__main__":
    main()
'''

GOOD_TEST = '''import unittest
from explorer import correlation, find_duplicates, missing_report, summary_stats


class T(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(missing_report([{"a": ""}]), {"a": 1})

    def test_dupes(self):
        self.assertEqual(len(find_duplicates([{"a": "1"}, {"a": "1"}])), 1)

    def test_corr(self):
        self.assertAlmostEqual(correlation([1, 2, 3], [2, 4, 6]), 1.0)

    def test_stats(self):
        self.assertEqual(summary_stats([2, 4])["mean"], 3)

    def test_no_dupes(self):
        self.assertEqual(find_duplicates([{"a": "1"}]), [])
'''

README = "# Explorer\n\n## Install\nRun pip install -r requirements.txt to set up.\n\n## Usage\n" + \
    "Run python explorer.py data.csv to see how it works. " * 10 + \
    "\n\n## Results\nThe metrics and findings on the sample dataset are described here. " * 3 + \
    "\n\n## Tests\nRun the unit tests with python -m unittest.\n"

GOOD_ZIP = {
    "explorer/explorer.py": GOOD_SOURCE,
    "explorer/tests/test_explorer.py": GOOD_TEST,
    "explorer/README.md": README,
    "explorer/requirements.txt": "pandas\n",
    "explorer/.gitignore": "__pycache__/\n",
}


def review(files, project=EXPLORER, **kw):
    return review_submission(project, load_submission("proj.zip", make_zip(files)), **kw)


class ReviewerTests(unittest.TestCase):
    def test_good_project_passes_with_high_score(self):
        report = review(GOOD_ZIP)
        self.assertTrue(report["passed"], report["gates"])
        self.assertGreaterEqual(report["score"], 90)
        self.assertEqual(report["coverage"], 100)
        self.assertEqual(report["gates"], [])
        self.assertEqual([c["name"] for c in report["categories"]],
                         ["Requirements", "Code quality", "Tests", "Documentation", "Packaging"])

    def test_wrapper_folder_is_stripped(self):
        sub = load_submission("p.zip", make_zip(GOOD_ZIP))
        self.assertIn("explorer.py", sub["files"])

    def test_empty_project_fails(self):
        report = review({"app.py": "print('hello')\n"})
        self.assertFalse(report["passed"])
        self.assertLess(report["score"], 40)
        self.assertTrue(report["next_steps"])

    def test_keywords_in_comments_and_strings_do_not_count(self):
        faked = "# argparse csv read_csv isna describe corr duplicated fillna\nTEXT = 'argparse read_csv isna describe corr duplicated fillna'\n"
        report = review({"app.py": faked})
        self.assertEqual(report["coverage"], 0)
        self.assertFalse(report["passed"])

    def test_syntax_error_blocks_pass(self):
        files = dict(GOOD_ZIP)
        files["explorer/broken.py"] = "def oops(:\n"
        report = review(files)
        self.assertFalse(report["passed"])
        self.assertTrue(any("syntax" in g.lower() for g in report["gates"]))

    def test_hardcoded_secret_blocks_pass_and_is_not_echoed(self):
        files = dict(GOOD_ZIP)
        files["explorer/config.py"] = 'API_KEY = "abcd1234efgh5678ijkl9012"\n'
        report = review(files)
        self.assertFalse(report["passed"])
        self.assertTrue(any("secret" in g.lower() for g in report["gates"]))
        self.assertNotIn("abcd1234efgh5678ijkl9012", json.dumps(report))

    def test_committed_env_file_is_flagged(self):
        files = dict(GOOD_ZIP)
        files["explorer/.env"] = "X=1\n"
        self.assertFalse(review(files)["passed"])

    def test_late_penalty(self):
        on_time = review(GOOD_ZIP)["score"]
        late = review(GOOD_ZIP, late=True)
        self.assertEqual(late["score"], on_time - 5)
        self.assertTrue(late["late"])

    def test_missing_tests_docs_and_packaging_cost_points(self):
        report = review({"explorer.py": GOOD_SOURCE})
        # a bare .py inside a zip is still a project archive, so tests/docs/packaging apply
        self.assertLess(report["score"], 70)
        self.assertFalse(report["passed"])

    def test_single_py_file_is_capped(self):
        sub = load_submission("explorer.py", GOOD_SOURCE.encode())
        report = review_submission(EXPLORER, sub)
        self.assertLessEqual(report["score"], 85)
        self.assertEqual([c["name"] for c in report["categories"]], ["Requirements", "Code quality"])
        self.assertTrue(report["adjustments"])

    def test_notebook_code_cells_are_reviewed_and_magics_ignored(self):
        nb = {"cells": [{"cell_type": "markdown", "source": ["# title"]},
                        {"cell_type": "code", "source": ["%matplotlib inline\n", "import argparse\n", "def clean(rows):\n", "    return rows\n"]}]}
        sub = load_submission("work.ipynb", json.dumps(nb).encode())
        report = review_submission(EXPLORER, sub)
        self.assertEqual(report["stats"]["python_files"], 1)
        labels = {f["label"] for c in report["categories"] for f in c["findings"] if f["status"] == "pass"}
        self.assertIn("Command-line interface", labels)

    def test_tiny_submission_gets_reduced_requirement_credit(self):
        tiny = "import argparse, csv\nmissing = describe = corr = duplicated = fillna = 1\n"
        report = review({"a.py": tiny})
        req = report["categories"][0]
        self.assertLess(req["earned"], req["max"] * 0.5)

    def test_seed_required_projects_check_reproducibility(self):
        linreg = TRACK["project_map"]["linreg-scratch"]
        src = "import numpy as np\n\ndef fit(X, y, lr=0.1):\n    '''x'''\n    return X\n"
        seeded = review({"m.py": src + "rng = np.random.default_rng(42)\n"}, project=linreg)
        unseeded = review({"m.py": src}, project=linreg)

        def repro(rep):
            return next(f for c in rep["categories"] for f in c["findings"] if f["label"] == "Reproducibility")
        self.assertEqual(repro(seeded)["status"], "pass")
        self.assertEqual(repro(unseeded)["status"], "fail")
        self.assertFalse(any(f["label"] == "Reproducibility"
                             for c in review({"m.py": src})["categories"] for f in c["findings"]))

    def test_every_project_review_config_works_against_an_empty_submission(self):
        for project in TRACK["projects"]:
            report = review({"x.py": "pass\n"}, project=project)
            self.assertFalse(report["passed"], project["id"])
            self.assertEqual(report["coverage"], 0, project["id"])

    def test_scope_tests_check_ignores_implementation_names(self):
        rag = TRACK["project_map"]["rag-assistant"]
        report = review({"app.py": "mock = 1\n"}, project=rag)
        finding = next(f for c in report["categories"] for f in c["findings"] if f["label"].startswith("Mocked LLM"))
        self.assertEqual(finding["status"], "fail")


class LoaderSafetyTests(unittest.TestCase):
    def test_rejects_wrong_extension_and_empty(self):
        with self.assertRaises(SubmissionError):
            load_submission("notes.txt", b"hi")
        with self.assertRaises(SubmissionError):
            load_submission("a.py", b"")

    def test_rejects_corrupt_zip(self):
        with self.assertRaises(SubmissionError):
            load_submission("a.zip", b"not a zip")

    def test_rejects_corrupt_notebook(self):
        with self.assertRaises(SubmissionError):
            load_submission("a.ipynb", b"{not json")

    def test_path_traversal_entries_are_skipped_not_used(self):
        data = make_zip({"../evil.py": "x = 1\n", "/abs.py": "y = 2\n", "ok.py": "z = 3\n"})
        sub = load_submission("a.zip", data)
        self.assertEqual(set(sub["files"]), {"ok.py"})
        self.assertEqual(len(sub["skipped"]), 2)

    def test_vendor_and_cache_dirs_are_ignored(self):
        data = make_zip({"app.py": "x = 1\n", "venv/lib/x.py": "y = 1\n", ".git/config": "z", "__pycache__/a.py": "q = 1\n"})
        self.assertEqual(set(load_submission("a.zip", data)["files"]), {"app.py"})

    def test_too_many_files_rejected(self):
        data = make_zip({f"f{i}.txt": "x" for i in range(reviewer.MAX_ARCHIVE_FILES + 1)})
        with self.assertRaises(SubmissionError):
            load_submission("a.zip", data)

    def test_zip_bomb_by_declared_size_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(3):
                zf.writestr(f"big{i}.txt", b"0" * (9 * 1024 * 1024))
        self.assertLess(len(buf.getvalue()), 200_000)  # tiny on the wire, 27 MB expanded
        with self.assertRaises(SubmissionError):
            load_submission("a.zip", buf.getvalue())

    def test_oversized_single_file_is_skipped(self):
        data = make_zip({"app.py": "x = 1\n", "huge.py": "#" + "a" * (reviewer.MAX_FILE_BYTES + 10)})
        sub = load_submission("a.zip", data)
        self.assertNotIn("huge.py", sub["files"])
        self.assertIn("huge.py", sub["skipped"])


if __name__ == "__main__":
    unittest.main()
