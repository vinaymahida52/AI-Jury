-- Closed learning loop schema for AI Jury (Neon / Postgres).

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    question TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'unknown',
    stop_reason TEXT NOT NULL DEFAULT '',
    agreement DOUBLE PRECISION NOT NULL DEFAULT 0,
    degraded JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    blackboard JSONB NOT NULL DEFAULT '{}'::jsonb,
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cases_created_at_idx ON cases (created_at DESC);
CREATE INDEX IF NOT EXISTS cases_trace_id_idx ON cases (trace_id);

CREATE TABLE IF NOT EXISTS verdicts (
    case_id TEXT PRIMARY KEY REFERENCES cases (id) ON DELETE CASCADE,
    outcome TEXT NOT NULL,
    answer TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    payload JSONB NOT NULL,
    rounds_used INT NOT NULL DEFAULT 0,
    tokens_used INT NOT NULL DEFAULT 0,
    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS failures (
    id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES cases (id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'unknown',
    expected TEXT NOT NULL,
    produced TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT '',
    signal TEXT NOT NULL,
    introduced_by TEXT,
    survived_rounds INT NOT NULL DEFAULT 0,
    verification_had_method BOOLEAN NOT NULL DEFAULT FALSE,
    open_cruxes JSONB NOT NULL DEFAULT '[]'::jsonb,
    belief_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    trace_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS failures_created_at_idx ON failures (created_at DESC);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    instruction TEXT NOT NULL,
    applies_to JSONB NOT NULL DEFAULT '[]'::jsonb,
    occurrences INT NOT NULL DEFAULT 0,
    example_failure_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS threads_updated_at_idx ON threads (updated_at DESC);

CREATE TABLE IF NOT EXISTS thread_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads (id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    case_id TEXT REFERENCES cases (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS thread_messages_thread_idx
    ON thread_messages (thread_id, created_at ASC);
