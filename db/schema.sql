-- Database schema for the AI Commitment Intelligence System (PostgreSQL).
--
-- Reconstructed from the live Neon database (information_schema, pg_constraint and pg_indexes), October 2026.
-- It creates the four tables the API uses. Run it once on an empty database, for example in the Neon SQL editor:
--     psql "$DATABASE_URL" -f db/schema.sql
-- then set DATABASE_URL on the API service. Nothing here contains data or secrets.
--
-- Design notes (each is relied on by the API and described in docs/PRIVACY_AND_SECURITY.md):
--   * Passwords and Gmail keys are stored only as hashes (password_hash, key_hash).
--   * There is no column for the full email text, subject, or any email address.
--   * Deleting a user cascades to api_keys, results and usage (ON DELETE CASCADE).
--   * api_keys.user_id is UNIQUE: at most one active key per user. Regenerating replaces it.
--   * results has no uniqueness constraint, so a retried email can in rare cases create a duplicate result.

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    userid        TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER     NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    key_hash   TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys (key_hash);

CREATE TABLE IF NOT EXISTS results (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    commitment_text TEXT,
    direction       TEXT,
    deadline_type   TEXT,
    deadline_text   TEXT,
    confidence      TEXT,
    sender          TEXT,
    recipient       TEXT,
    urgency_score   REAL,
    explanation     TEXT,
    source          TEXT                 DEFAULT 'unspecified',
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_results_user_id ON results (user_id);

CREATE TABLE IF NOT EXISTS usage (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    usage_date    DATE    NOT NULL DEFAULT CURRENT_DATE,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, usage_date)
);
