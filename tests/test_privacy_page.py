"""Task 8 tests: Privacy & consent page, and guards that keep the privacy text honest against the real code.
Layout: tests/test_privacy_page.py  tests  app/frontend.py, app/main.py, src/auth.py.
Run:  python -m pytest -q tests/test_privacy_page.py"""
import os
import re

import pytest
import requests
from streamlit.testing.v1 import AppTest

os.environ["WAKE_MAX_SECONDS"] = "1"
os.environ["WAKE_POLL_SECONDS"] = "0"
os.environ["API_URL"] = "https://api.example.test"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FRONTEND = os.environ.get("FRONTEND_PATH") or os.path.join(ROOT, "app", "frontend.py")
MAIN_PY = os.path.join(ROOT, "app", "main.py")
AUTH_PY = os.path.join(ROOT, "src", "auth.py")


def read(p):
    return open(p, encoding="utf-8").read()


# ------------------------------------------------------------------ minimal mock API
class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b, self.ok = status, body or {}, status < 400

    def json(self):
        return self._b

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(str(self.status_code))


class Fake:
    def get(self, url, timeout=None, **kw):
        assert url.endswith("/health"), url
        return Resp(200, {"status": "ok", "paused": False})

    def request(self, method, url, **kw):
        path = url.replace(os.environ["API_URL"], "")
        if path == "/me":
            return Resp(200, {"userid": "alice", "created_at": "2026-10-01T10:00:00"})
        if path == "/usage":
            return Resp(200, {"daily_limit": 30, "max_text_chars": 8000, "retention_days": 7, "max_results": 200,
                              "used_today": 0, "resets_in_seconds": 3600, "paused": False})
        if path == "/results":
            return Resp(200, {"results": []})
        if path == "/apikey":
            return Resp(200, {"has_key": False, "created_at": None})
        return Resp(200, {})


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    fake = Fake()
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr(requests, "request", fake.request)


def run(state=None):
    at = AppTest.from_file(FRONTEND, default_timeout=30)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    return at


def page_text(at):
    out = []
    for kind in ("markdown", "caption", "info", "warning", "success", "subheader", "title"):
        out += [getattr(e, "value", "") or "" for e in at.get(kind)]
    return "\n".join(out)


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[*`_#>|]", " ", t)).strip().lower()


REQUIRED_TOPICS = [
    "gemini", "free tier", "human reviewers",                       # data use
    "confidential", "other people's emails",                        # responsibility
    "not for use from the eea, switzerland or the uk",              # geographic restriction
    "does not detect your location",                                # honest: not enforced
    "bcrypt", "sha-256",                                            # how secrets are stored
    "not anonymised",                                               # honest about stored fragments
    "not stored in the database", "server logs",                    # raw email not stored
    "render", "neon", "project owner", "administrative access",     # third parties incl. developer
    "7 days", "delete my data", "delete my account",                # retention and deletion
    "12 hours", "5 wrong passwords", "10 minutes",                  # session + throttle
    "no password reset", "no email",                                # no recovery
    "commitmentai-send", "never receives your google password",     # gmail
    "30 emails per day", "8,000 characters", "200 stored results", "15 accounts",
    "can't be cancelled early",                                     # JWT limitation
    "not had a professional security audit",                        # no fake guarantees
    "your consent", "withdraw",
]


# ================================================================== the page
def test_privacy_page_renders_after_login_with_all_required_topics():
    at = run({"token": "t", "userid": "alice", "page": "Privacy & consent"})
    assert not at.exception
    assert any("Privacy & consent" in t.value for t in at.title)
    t = norm(page_text(at))
    missing = [x for x in REQUIRED_TOPICS if x not in t]
    assert not missing, missing


def test_sidebar_has_privacy_option_and_keeps_existing_pages_in_order():
    at = run({"token": "t", "userid": "alice"})
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == ["Dashboard", "Connect Gmail", "Account", "Privacy & consent"]


def test_existing_pages_still_render():
    for page, marker in (("Dashboard", None), ("Account", "Delete my account"), ("Connect Gmail", "Step 1")):
        at = run({"token": "t", "userid": "alice", "page": page})
        assert not at.exception, page
        if marker:
            assert marker in page_text(at) or any(marker in b.label for b in at.button), page


def test_account_and_connect_pages_point_to_the_notice_instead_of_duplicating_it():
    acct = page_text(run({"token": "t", "userid": "alice", "page": "Account"}))
    assert "Privacy & consent" in acct
    conn = page_text(run({"token": "t", "userid": "alice", "page": "Connect Gmail"}))
    assert "Privacy & consent" in conn
    assert "bcrypt" not in conn and "bcrypt" not in acct          # the long text lives in one place only


# ================================================================== before login
def test_notice_is_readable_before_creating_an_account():
    at = run()
    assert not at.exception
    labels = [e.proto.label for e in at.get("expander")]
    assert any("Privacy & consent" in l for l in labels)
    t = norm(page_text(at))
    assert "not for use from the eea, switzerland or the uk" in t
    assert "bcrypt" in t                                          # full notice is inside the expander


def test_signup_still_requires_the_consent_tickbox_and_keeps_old_disclosures():
    at = run()
    t = norm(page_text(at))
    for needed in ("no email, no password reset", "gemini", "free", "7 days", "30 emails per day"):
        assert needed in t, needed
    assert any("I have read and understand the above" in c.label for c in at.checkbox)
    # submitting without ticking must not create an account
    inputs = at.text_input
    signup_fields = [i for i in inputs if i.label in ("Choose a userid", "Choose a password", "Confirm password")]
    assert len(signup_fields) == 3
    signup_fields[0].set_value("newuser")
    signup_fields[1].set_value("password123")
    signup_fields[2].set_value("password123")
    [b for b in at.button if b.label == "Create account"][0].click().run()
    assert any("tick the box" in e.value for e in at.error)
    assert not at.session_state["token"] if "token" in at.session_state else True


# ================================================================== claim guards: text vs real code
def _int(pattern, text):
    m = re.search(pattern, text)
    assert m, pattern
    return int(m.group(1))


@pytest.mark.skipif(not os.path.exists(MAIN_PY), reason="app/main.py not found")
def test_numbers_in_the_notice_match_backend_defaults():
    main, auth, fe = read(MAIN_PY), read(AUTH_PY), read(FRONTEND)
    assert _int(r'_env_int\("MAX_TEXT_CHARS",\s*(\d+)\)', main) == _int(r"DEFAULT_MAX_CHARS\s*=\s*(\d+)", fe)
    assert _int(r'_env_int\("DAILY_LIMIT_PER_USER",\s*(\d+)\)', main) == _int(r"NOTICE_DAILY_LIMIT\s*=\s*(\d+)", fe)
    assert _int(r'_env_int\("RESULT_RETENTION_DAYS",\s*(\d+)\)', main) == _int(r"NOTICE_RETENTION_DAYS\s*=\s*(\d+)", fe)
    assert _int(r'_env_int\("MAX_RESULTS_PER_USER",\s*(\d+)\)', main) == _int(r"NOTICE_MAX_RESULTS\s*=\s*(\d+)", fe)
    assert _int(r"MAX_USER_ACCOUNTS\s*=\s*(\d+)", main) == _int(r"NOTICE_MAX_ACCOUNTS\s*=\s*(\d+)", fe)
    assert _int(r"USAGE_HISTORY_DAYS\s*=\s*(\d+)", main) == _int(r"NOTICE_USAGE_HISTORY_DAYS\s*=\s*(\d+)", fe)
    assert _int(r"LOGIN_MAX_FAILURES\s*=\s*(\d+)", main) == _int(r"NOTICE_LOGIN_MAX_FAILURES\s*=\s*(\d+)", fe)
    assert _int(r"LOGIN_WINDOW_SECONDS\s*=\s*(\d+)\s*\*\s*60", main) == _int(r"NOTICE_LOGIN_WINDOW_MINUTES\s*=\s*(\d+)", fe)
    assert _int(r"SESSION_TTL_SECONDS\s*=\s*(\d+)\s*\*\s*60\s*\*\s*60", auth) == _int(r"NOTICE_SESSION_HOURS\s*=\s*(\d+)", fe)


@pytest.mark.skipif(not os.path.exists(MAIN_PY), reason="app/main.py not found")
def test_notice_claims_about_storage_hold_in_the_code():
    main, auth = read(MAIN_PY), read(AUTH_PY)
    # passwords: bcrypt hash only
    hp = re.search(r"def hash_password\(.*?(?=\n\ndef |\n\n\n)", auth, re.S).group(0)
    assert "bcrypt.hashpw" in hp and "password_hash" in main
    sp = re.search(r"def create_session_token\(.*?(?=\n\ndef |\n\n\n)", auth, re.S).group(0)
    assert "SESSION_TTL_SECONDS" in sp                       # sessions expire (notice: 12 hours)
    ak = re.search(r"def hash_api_key\(.*", auth, re.S).group(0)
    assert "sha256" in ak
    # API key: stored as SHA-256 hash
    assert "key_hash" in main
    # the INSERT into results has no column for the raw email text
    ins = re.search(r'"INSERT INTO results \(user_id, (.*?)\) "', main, re.S).group(1)
    cols = [c.strip() for c in re.sub(r'["\s]+', " ", ins).split(",")]
    assert cols and not any(c in ("text", "email_text", "body", "raw_text", "subject") for c in cols), cols
    assert "commitment_text" in cols and "sender" in cols and "recipient" in cols   # what the notice says IS stored
    # retention filter is applied when reading, and a purge deletes physically
    assert "processed_at > now() - make_interval" in main and "DELETE FROM results WHERE processed_at <" in main
    # login errors are generic (no userid enumeration) and a dummy hash equalises timing
    assert 'detail="Invalid userid or password."' in main and "burn_dummy_check" in main + auth


@pytest.mark.skipif(not os.path.exists(MAIN_PY), reason="app/main.py not found")
def test_server_never_logs_email_text():
    """The notice says server logs hold timings, counts and warnings only. Fail if any print/logging call in the
    API interpolates a variable that could hold submitted or extracted text."""
    main = read(MAIN_PY)
    calls = re.findall(r"print\((.*?)\)\s*\n", main, re.S)
    assert calls
    placeholders = [p for c in calls for p in re.findall(r"\{([^{}]*)\}", c)]
    assert placeholders
    forbidden = re.compile(r"payload|\btext\b|\.text\b|body|ranked|commitment|subject|email_|prompt|response")
    bad = [p for p in placeholders
           if forbidden.search(p) and not re.fullmatch(r"len\([A-Za-z_]+\)", p.strip())]   # len(x) is only a count
    assert not bad, bad
    assert "logging." not in main and "logger." not in main


def test_gmail_script_sends_only_the_latest_message_body():
    fe = read(FRONTEND)
    assert "getPlainBody()" in fe and "substring(0, MAX_CHARS)" in fe
    assert "getSubject" not in fe and "getFrom" not in fe
