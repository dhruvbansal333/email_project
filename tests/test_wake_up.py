"""Tests for the Render wake-up gating + Gmail Connect page redesign (frontend.py).
Network is mocked; AppTest runs the real Streamlit script. Run:  python -m pytest -q test_task7b.py"""
import ast
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import textwrap
import time

import pytest
import requests
from streamlit.testing.v1 import AppTest

os.environ["WAKE_MAX_SECONDS"] = "1"
os.environ["WAKE_POLL_SECONDS"] = "0"
os.environ["API_URL"] = "https://api.example.test"

HERE = os.path.dirname(os.path.abspath(__file__))
# Repo layout: tests/test_wake_up.py tests ../app/frontend.py
NEW = os.environ.get("FRONTEND_PATH") or os.path.join(HERE, "..", "app", "frontend.py")
# Optional: a copy of the frontend from BEFORE this change, to prove the script text is byte-identical.
OLD = os.environ.get("FRONTEND_BEFORE_PATH") or os.path.join(HERE, "frontend_before.py")
needs_old = pytest.mark.skipif(not os.path.exists(OLD), reason="no frontend_before.py to compare against")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed (copy-button JS tests)")
KEY = "cai_TESTKEY_1234567890abcdef"


# ------------------------------------------------------------------ mock API
class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(str(self.status_code))


class FakeApi:
    def __init__(self, health_fail_first=0, health_always_fail=False):
        self.health_calls = 0
        self.fail_first = health_fail_first
        self.always_fail = health_always_fail
        self.paths = []

    def get(self, url, timeout=None, **kw):
        if url.endswith("/health"):
            self.health_calls += 1
            if self.always_fail or self.health_calls <= self.fail_first:
                raise requests.exceptions.ConnectionError("asleep")
            return FakeResp(200, {"status": "ok", "paused": False})
        raise AssertionError(url)

    def request(self, method, url, **kw):
        path = url.replace(os.environ["API_URL"], "")
        self.paths.append((method, path))
        if path == "/apikey" and method == "GET":
            return FakeResp(200, {"has_key": True, "created_at": "2026-10-01T10:00:00"})
        if path == "/results":
            return FakeResp(200, {"results": [], "usage": {}})
        return FakeResp(200, {})


CUR = {"fake": None}


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    CUR["fake"] = None
    monkeypatch.setattr(requests, "get", lambda *a, **k: CUR["fake"].get(*a, **k))
    monkeypatch.setattr(requests, "request", lambda *a, **k: CUR["fake"].request(*a, **k))
    yield


def run_app(fake, path=NEW, state=None):
    CUR["fake"] = fake
    at = AppTest.from_file(path, default_timeout=30)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    return at, fake


def logged_in(fake=None, fresh=True, **extra):
    fake = fake or FakeApi()
    state = {"token": "tok", "userid": "alice", "page": "Connect Gmail"}
    if fresh:
        state["fresh_key"] = KEY
    state.update(extra)
    return run_app(fake, state=state)


def all_text(at):
    """Every visible text in the rendered page, expanders included."""
    out = []
    for kind in ("markdown", "caption", "info", "warning", "success", "error", "subheader", "title", "text", "code"):
        for el in at.get(kind):
            v = getattr(el, "value", None) or getattr(el, "proto", None) and getattr(el.proto, "body", "")
            if v:
                out.append(v)
    for el in at.get("expander"):
        out.append(el.proto.label)
    for b in at.button:
        out.append(b.label)
    return "\n".join(out)


def norm(t):
    t = re.sub(r"[*`_#>]", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


# ------------------------------------------------------------------ extracted helpers
def load_helpers(path):
    """Pull SCRIPT_TEMPLATE / build_script / copy_button_html out of a frontend file without running the app."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("SCRIPT_TEMPLATE",) for t in node.targets):
            keep.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in ("build_script", "copy_button_html"):
            keep.append(node)
    ns = {"json": json, "html": htmllib}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    return ns


# ================================================================== wake-up gating (login screen)
def test_wake_ready_immediately_shows_forms_no_retry():
    at, fake = run_app(FakeApi())
    assert not at.exception
    assert len(at.tabs) == 2 and at.text_input
    assert "🔄 Retry" not in [b.label for b in at.button]
    assert fake.health_calls == 1 and fake.paths == []        # wake call is /health only, nothing else


def test_wake_delayed_then_ok_continues_by_itself():
    os.environ["WAKE_MAX_SECONDS"] = "5"
    try:
        at, fake = run_app(FakeApi(health_fail_first=3))
    finally:
        os.environ["WAKE_MAX_SECONDS"] = "1"
    assert not at.exception
    assert at.text_input, "forms should appear once the API answers"
    assert fake.health_calls == 4


def test_wake_never_answers_shows_error_retry_and_no_forms():
    at, fake = run_app(FakeApi(health_always_fail=True))
    assert not at.exception
    assert "🔄 Retry" in [b.label for b in at.button]
    assert not at.text_input, "login must stay disabled until the API is ready"
    assert any("hasn't answered" in e.value for e in at.error)
    assert fake.paths == []                                    # never touched /login, /process etc.


def test_retry_succeeds_once_server_is_up():
    fake = FakeApi(health_always_fail=True)
    CUR["fake"] = fake
    if True:
        at = AppTest.from_file(NEW, default_timeout=30).run()
        assert not at.text_input
        fake.always_fail = False                               # server finished waking up
        at.button[0].click().run()
    assert not at.exception and at.text_input and "🔄 Retry" not in [b.label for b in at.button]


def test_wake_does_not_use_process_endpoint():
    src = open(NEW, encoding="utf-8").read()
    wake_fns = re.search(r"def _health_once.*?def _clear_session", src, re.S).group(0)
    assert "/process" not in wake_fns and "/health" in wake_fns


def test_legacy_secret_not_referenced():
    src = open(NEW, encoding="utf-8").read()
    assert "os.environ" in src and "INGESTION_SECRET" not in src.replace("The old INGESTION_SECRET variable is no longer used by this file.", "")


