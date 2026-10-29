-- SkillPath schema. All statements are idempotent so the app can apply it on every start.
-- Timestamps are ISO-8601 UTC strings.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    track_id      TEXT    NOT NULL DEFAULT 'ai-ml',
    cycle_weeks   INTEGER NOT NULL DEFAULT 2 CHECK (cycle_weeks BETWEEN 1 AND 12),
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id     TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'needs_revision', 'passed', 'abandoned')),
    cycle_weeks    INTEGER NOT NULL,
    started_at     TEXT    NOT NULL,
    due_at         TEXT    NOT NULL,
    extended_count INTEGER NOT NULL DEFAULT 0,
    completed_at   TEXT,
    best_score     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(user_id, status);

CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename      TEXT    NOT NULL,
    stored_path   TEXT,
    submitted_at  TEXT    NOT NULL,
    late          INTEGER NOT NULL DEFAULT 0,
    score         INTEGER NOT NULL,
    passed        INTEGER NOT NULL,
    report_json   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON submissions(assignment_id);

CREATE TABLE IF NOT EXISTS concept_progress (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id TEXT    NOT NULL,
    read_at    TEXT    NOT NULL,
    PRIMARY KEY (user_id, concept_id)
);

CREATE TABLE IF NOT EXISTS lc_progress (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_no INTEGER NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('todo', 'attempted', 'solved')),
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, problem_no)
);

CREATE TABLE IF NOT EXISTS industry_progress (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_id TEXT    NOT NULL,
    answer      TEXT    NOT NULL,
    answered_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, question_id)
);
