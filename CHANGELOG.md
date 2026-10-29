# Changelog

All notable changes to SkillPath are documented here. Versions follow [SemVer](https://semver.org/).

## [1.0.0] - First stable release
### Added
- Full README: quick start, how cycles, mastery and scoring work, project layout, how to add a new career track, security notes.
### Verified
- 103 automated tests, plus an end-to-end run against the live server with CSRF protection on (sign up, set cycle, start, upload, pass, next recommendation, log out).

## [0.5.0] - Learning hub
### Added
- Concept library: 14 primers with the idea, key points and pitfalls, and a "mark as read" toggle.
- LeetCode tracker (todo / attempted / solved) with status and difficulty filters; every problem lists the concepts that use it and why.
- Industry-style questions answered in writing, with a "what a strong answer covers" self-check revealed after answering.
- Mastery now moves with real activity, which changes project readiness and which project is recommended next.
- Project briefs link straight to the primers they require.
### Changed
- Shared `load_state` helper replaces duplicated state loading.

## [0.4.0] - Review and scoring
### Added
- Submit a .zip project, a .py file or a .ipynb notebook from the dashboard or project page.
- Static reviewer that never runs submitted code: 100-point rubric covering requirements (matched on parsed names, so comments cannot game it), code quality, tests, docs and packaging.
- Pass gates: files must parse, no hard-coded secrets, and at least 60% of requirements found. Pass mark is 70.
- Late penalty (-5), single-file cap (85), reduced credit for near-empty submissions.
- Safe archive handling: file-count and size limits, zip-bomb check, path-traversal entries skipped, encrypted zips refused.
- Report page with per-check findings and "how to fix" guidance; passing triggers the next-project recommendation.
- Uploads are stored privately per user; reports are visible only to their owner.

## [0.3.0] - Project cycles
### Added
- Configurable cycle length (1-12 weeks, default 2) in Settings; each project gets that long to build and submit.
- Dashboard with the current project, countdown, progress bar, a Learn/Build/Polish/Submit schedule and a LeetCode sprint sized to the cycle.
- Next-project recommender: respects prerequisites, steps up difficulty after a 90+ score, and targets least-practiced concepts.
- Concept mastery scoring blending primer reading, LeetCode, industry questions and applied projects.
- Roadmap by level (passed / in progress / available / locked), project briefs with requirements, concept primers and resume bullet.
- Start, extend (tracked) and drop actions; one open project at a time; dates shown in the browser's timezone.

## [0.2.0] - AI/ML curriculum
### Added
- Track loader and validator (`skillpath/content.py`): checks ids, LeetCode references, prerequisite graph (no cycles) and review-check regexes.
- AI/ML track: 14 concept primers, each linked to 4-5 LeetCode problems (with a one-line reason for the connection) and 3 industry-style questions with self-check key points.
- 12 projects across 5 levels (data explorer, linear/logistic regression, Naive Bayes, random forest, k-means, neural net, semantic search, CNN, RAG assistant, tiny GPT, production model API), each with requirements, deliverables, stretch goals, a resume bullet and automated review checks.
- Content integrity tests.

## [0.1.0] - Foundation
### Added
- Flask application factory with persistent per-install secret key.
- SQLite schema (users, assignments, submissions, concept/LeetCode/industry progress) applied idempotently on start.
- Account registration, login and logout with salted password hashing.
- CSRF protection on every state-changing request, open-redirect guard, and a per-app login throttle.
- Base layout, landing page, error pages and a light/dark design system.
- stdlib `unittest` suite for auth and security helpers (no extra test dependencies).
