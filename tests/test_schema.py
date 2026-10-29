"""Static checks that db/schema.sql and the SQL in app/main.py agree, and that the privacy-relevant design holds.
No database is needed. Run:  python -m pytest -q tests/test_schema.py"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def parse_schema(sql):
    sql = re.sub(r"--[^\n]*", "", sql)
    tables = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", sql, re.S):
        cols = {}
        for line in body.strip().splitlines():
            line = line.strip().rstrip(",")
            m = re.match(r"(\w+)\s+([A-Z]+)(.*)", line)
            if m and m.group(1).upper() not in ("PRIMARY",):
                cols[m.group(1)] = m.group(3)
        tables[name] = {"cols": cols, "body": body}
    return tables


TABLES = parse_schema(SCHEMA)


def sql_text(py):
    """Join implicit string concatenation so multi-line SQL strings become one line."""
    return re.sub(r'"\s*\n\s*"', "", py)


def test_the_four_tables_exist():
    assert set(TABLES) == {"users", "api_keys", "results", "usage"}


def test_every_insert_in_the_api_uses_existing_columns():
    text = sql_text(MAIN)
    found = re.findall(r"INSERT INTO (\w+)\s*\(([^)]*)\)", text)
    assert found, "no INSERT statements found; the parser may need updating"
    for table, cols in found:
        assert table in TABLES, table
        for c in [x.strip() for x in cols.split(",")]:
            assert c in TABLES[table]["cols"], f"{table}.{c} is used in app/main.py but not defined in db/schema.sql"


def test_every_table_the_api_queries_exists():
    text = sql_text(MAIN)
    names = set(re.findall(r'"\s*(?:SELECT|UPDATE|DELETE FROM|INSERT INTO)[^"]*?\b(?:FROM|(?<!DO )UPDATE|INTO|JOIN)\s+(?!SET\b)(\w+)', text))
    names |= set(re.findall(r"\b(?:DELETE FROM|INSERT INTO)\s+(\w+)", text))
    names -= {"now", "make_interval"}
    unknown = {n for n in names if n not in TABLES}
    assert not unknown, unknown


def test_deleting_a_user_cascades_everywhere():
    for t in ("api_keys", "results", "usage"):
        assert re.search(r"REFERENCES users\(id\) ON DELETE CASCADE", TABLES[t]["body"]), t


def test_one_key_per_user_and_unique_userid_and_hashed_secrets():
    assert "UNIQUE" in TABLES["api_keys"]["cols"]["user_id"]
    assert "UNIQUE" in TABLES["users"]["cols"]["userid"]
    assert "password_hash" in TABLES["users"]["cols"] and "password" not in TABLES["users"]["cols"]
    assert "key_hash" in TABLES["api_keys"]["cols"] and "api_key" not in TABLES["api_keys"]["cols"]
    assert re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys \(key_hash\)", SCHEMA)


def test_no_column_can_hold_the_raw_email_or_consent():
    """The privacy notice says the full email text is not stored and that no consent record is kept."""
    forbidden = {"email_text", "body", "raw_text", "text", "subject", "email", "sender_email", "message",
                 "consent", "consented_at", "ip", "ip_address"}
    for t, info in TABLES.items():
        assert not forbidden & set(info["cols"]), (t, forbidden & set(info["cols"]))


def test_results_columns_match_what_the_privacy_notice_lists():
    assert set(TABLES["results"]["cols"]) == {
        "id", "user_id", "commitment_text", "direction", "deadline_type", "deadline_text", "confidence",
        "sender", "recipient", "urgency_score", "explanation", "source", "processed_at"}


def test_schema_is_idempotent_by_construction():
    assert SCHEMA.count("CREATE TABLE") == SCHEMA.count("CREATE TABLE IF NOT EXISTS")
    assert SCHEMA.count("CREATE INDEX") == SCHEMA.count("CREATE INDEX IF NOT EXISTS")
    assert SCHEMA.count("CREATE UNIQUE INDEX") == SCHEMA.count("CREATE UNIQUE INDEX IF NOT EXISTS")
