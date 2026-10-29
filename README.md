# SkillPath

A project-driven learning app for breaking into a tech career. You pick a track
(version 1: **AI / Machine Learning**), set how many weeks each project cycle lasts, and
SkillPath:

1. **Assigns a project** sized to your cycle (for example 2 weeks to build and submit).
2. **Teaches the concepts first**: every project links to primers on what you must know before coding.
3. **Ties the concepts to problem solving**: each concept maps to LeetCode problems *and*
   industry-style questions, so you build a portfolio and interview skill together.
4. **Reviews your submission**, scores it out of 100 and explains how to fix what is missing.
5. **Recommends the next project** based on your score and your weakest concepts.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app wsgi run               # open http://127.0.0.1:5000
```

Run the tests (standard library only, no extra packages):

```bash
python3 -m unittest discover -s tests -t .
```

Data lives in `instance/` (SQLite database, uploaded submissions, a generated secret key).
That folder is git-ignored. Set `SKILLPATH_SECRET_KEY` to supply your own secret.

## How it works

### The cycle
You choose 1 to 12 weeks in **Settings** (default 2). Starting a project gives you that long.
The dashboard shows a countdown, a Learn / Build / Polish / Submit schedule, and a **LeetCode
sprint** (about two problems per week, drawn from the project's concepts, easiest first).
You can extend a deadline (it is tracked) or drop a project. One project is open at a time.

### The 12 AI/ML projects
| Level | Projects |
|---|---|
| 1 Foundations | CSV Data Explorer CLI, Linear Regression from Scratch |
| 2 Core models | Logistic Regression + Evaluation Suite, Naive Bayes Spam Filter |
| 3 Intermediate | Decision Tree & Random Forest, Customer Segmentation (k-means/kNN), Neural Network from Scratch |
| 4 Applied systems | Semantic Search Engine, Image Classifier (CNN vs transfer learning), RAG Question-Answering Assistant |
| 5 Advanced | Tiny GPT (character-level transformer), Production Model API with drift monitoring |

Projects have prerequisites; a 90+ score steps the difficulty up, otherwise you continue along
the path, and ties are broken toward the concepts you have practiced least.

### Concepts, LeetCode and industry questions
14 concept primers, each with 4-5 LeetCode problems (with a one-line reason each problem
belongs there) and 3 industry-style questions. You answer questions in writing, then compare
with "what a strong answer covers". **Mastery** per concept blends reading the primer (15%),
LeetCode (40%), written answers (25%) and applying it in a passed project (20%).

### The automated review (100 points)
| Category | Points | What it checks |
|---|---|---|
| Requirements | 45 | The project's required pieces, found by parsing your code (names of functions, classes, variables, imports). Keywords in comments or strings never count. |
| Code quality | 20 | Parses cleanly, docstrings, function size, no bare `except` / wildcard imports / `eval`, random seed set where results depend on randomness |
| Tests | 15 | Test files, number of tests, assertions *(zip uploads)* |
| Documentation | 10 | README present, substantial, covers setup, usage, results *(zip uploads)* |
| Packaging | 10 | Dependency file, `.gitignore`, no committed secrets *(zip uploads)* |

Pass mark is **70**, and a pass also requires: all files parse, no hard-coded secrets, and at
least 60% of requirements found. Submitting after the deadline costs 5 points; single-file
uploads are capped at 85. Submit a `.zip`, a `.py` file or a `.ipynb` notebook.

**What the review cannot do.** It never runs your code, so it checks structure and engineering
habits, not whether your algorithm is correct. A pass means "built the way the brief describes".
Write your own tests to prove correctness.

## Project layout

```
skillpath/
  __init__.py        app factory
  auth.py            register / login / logout, throttling
  security.py        CSRF, login throttle, safe-redirect check
  db.py, schema.sql  SQLite helpers and schema
  content.py         loads and validates tracks
  mastery.py         concept mastery scoring
  recommender.py     next-project selection
  planning.py        cycle schedule and LeetCode sprint
  progress.py        reads a user's state
  cycles.py          dashboard, roadmap, project pages, settings
  learn.py           concept pages, LeetCode tracker, practice questions
  submissions.py     upload and report pages
  reviewer.py        static review engine
  tracks/ai_ml/      the curriculum (plain JSON)
  templates/, static/
tests/               unittest suite
```

## Adding a new track (for example Web Development, Cybersecurity)

1. Copy `skillpath/tracks/ai_ml/` to a new folder and edit `meta.json`, `leetcode.json`,
   `concepts/*.json` and `projects/*.json`.
2. Add the track id to `TRACK_IDS` in `skillpath/content.py`.
3. Run the tests: `tests/test_content.py` validates every registered track (unknown concept
   or prerequisite ids, missing LeetCode entries, prerequisite cycles, bad review patterns).

Each project's `review.checks` entries use regular expressions matched against names in the
code (`"^fit$"` matches exactly `fit`; `"grad"` matches any name containing `grad`).
Add `"files": true` to match file names (for example a Dockerfile) or `"scope": "tests"` to
look only in test files.

## Security notes

- Passwords are hashed with Werkzeug; CSRF tokens protect every POST; login attempts are throttled.
- Uploaded code is only parsed, never executed. Archives are bounded (file count, expanded size),
  zip entries with unsafe paths are skipped, and encrypted zips are refused.
- Reports are visible only to the account that submitted. Uploads are stored privately.
- For production use a real WSGI server (for example `gunicorn wsgi:app`) behind HTTPS and set
  `SKILLPATH_SECRET_KEY`. The login throttle is per process; use a shared store if you run several workers.

## Roadmap

More tracks (web, mobile, cybersecurity, data engineering), review checks that run a project's
own tests in a sandbox, spaced-repetition for concepts, and sharing a portfolio page.

## License

MIT
