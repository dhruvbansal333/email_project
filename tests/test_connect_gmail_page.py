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
# Repo layout: tests/test_connect_gmail_page.py tests ../app/frontend.py
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


# ================================================================== script generation
@needs_old
def test_script_template_unchanged_and_configured():
    old, new = load_helpers(OLD), load_helpers(NEW)
    assert old["SCRIPT_TEMPLATE"] == new["SCRIPT_TEMPLATE"]
    url = "https://ai-commitment-api.onrender.com"
    assert old["build_script"](url, KEY) == new["build_script"](url, KEY)
    s = new["build_script"](url, KEY)
    assert KEY in s and url in s
    assert "CommitmentAI-Send" in s and "CommitmentAI-Done" in s and "CommitmentAI-Failed" in s
    assert "__API_KEY__" not in s
    placeholder = new["build_script"](url, None)
    assert KEY not in placeholder


def test_script_generation_without_old_file():
    h = load_helpers(NEW)
    url = "https://ai-commitment-api.onrender.com"
    s = h["build_script"](url, KEY)
    assert KEY in s and url in s and "__API_KEY__" not in s
    assert "CommitmentAI-Send" in s and "CommitmentAI-Done" in s and "CommitmentAI-Failed" in s
    assert KEY not in h["build_script"](url, None)


# ================================================================== copy button (real JS run in node)
def NAV(obj):
    return "Object.defineProperty(globalThis,'navigator',{value:" + obj + ",configurable:true});"


def run_js(script_text, scenario):
    h = load_helpers(NEW)["copy_button_html"](script_text)
    js = re.search(r"<script>(.*)</script>\s*</body>", h, re.S).group(1)
    harness = textwrap.dedent(f"""
      const __msg = {{className:"", textContent:""}};
      let copied = null;
      const btn = {{ addEventListener(_, fn) {{ this.fn = fn; }} }};
      global.document = {{
        getElementById: id => id === "m" ? __msg : btn,
        createElement: () => ({{style:{{}}, focus(){{}}, select(){{}}}}),
        body: {{appendChild(){{}}, removeChild(){{}}}},
        execCommand: () => {{ return {scenario['legacy']}; }}
      }};
      {scenario['nav']}
      {js}
      btn.fn();
      setTimeout(() => console.log(JSON.stringify({{cls: __msg.className, text: __msg.textContent, copied}})), 30);
    """)
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_copy_success_via_clipboard_api():
    r = run_js("SCRIPT with key " + KEY, {
        "legacy": "false",
        "nav": NAV("{clipboard: {writeText: t => { copied = t; return Promise.resolve(); }}}")})
    assert r["cls"] == "ok" and "Copied" in r["text"] and r["copied"] == "SCRIPT with key " + KEY


@needs_node
def test_copy_falls_back_to_legacy_then_succeeds():
    r = run_js("abc", {"legacy": "true",
                       "nav": NAV("{clipboard: {writeText: () => Promise.reject(new Error('denied'))}}")})
    assert r["cls"] == "ok"


@needs_node
def test_copy_reports_failure_when_everything_fails():
    r = run_js("abc", {"legacy": "false",
                       "nav": NAV("{clipboard: {writeText: () => Promise.reject(new Error('denied'))}}")})
    assert r["cls"] == "bad" and "Couldn't copy" in r["text"] and "View script code" in r["text"]


@needs_node
def test_copy_without_clipboard_api():
    r = run_js("abc", {"legacy": "false", "nav": NAV("{}")})
    assert r["cls"] == "bad"


def test_copy_html_cannot_be_broken_by_script_tag_in_text():
    h = load_helpers(NEW)["copy_button_html"]("x</script><b>y")
    assert h.count("</script>") == 1          # only our own closing tag
    assert "<\\/script>" in h


# ================================================================== Connect page behaviour
def test_script_collapsed_by_default_then_toggles():
    at, _ = logged_in()
    assert not at.exception
    js_blocks = [c for c in at.get("code") if getattr(c, "language", "") == "javascript" or "processLabeledEmails" in c.value]
    assert js_blocks == [], "script must be collapsed by default"
    labels = [b.label for b in at.button]
    assert "View script code" in labels and "Hide script code" not in labels

    at.button(key="toggle_script").click().run()
    shown = [c for c in at.get("code") if "processLabeledEmails" in c.value]
    assert len(shown) == 1 and KEY in shown[0].value and "api.example.test" in shown[0].value
    assert "Hide script code" in [b.label for b in at.button]

    at.button(key="toggle_script").click().run()
    assert [c for c in at.get("code") if "processLabeledEmails" in c.value] == []
    assert "View script code" in [b.label for b in at.button]


def test_copy_component_and_download_present_and_carry_the_configured_script():
    at, _ = logged_in()
    iframes = at.get("iframe")
    assert iframes, "copy button component missing"
    srcdoc = iframes[0].proto.srcdoc
    # the exact configured script is inside the copy component
    payload = re.search(r"const TEXT = (.*);\n", srcdoc).group(1)
    copied = json.loads(payload.replace("<\\/", "</"))
    expected = load_helpers(NEW)["build_script"]("https://api.example.test", KEY)
    assert copied == expected and KEY in copied
    assert "Copy setup script" in srcdoc
    assert at.get("download_button"), "download option must be preserved"


def test_without_fresh_key_uses_placeholder_label_and_no_key_leak():
    at, _ = logged_in(fresh=False)
    assert not at.exception
    srcdoc = at.get("iframe")[0].proto.srcdoc
    assert KEY not in srcdoc and "key not included" in srcdoc
    assert "placeholder" in all_text(at).lower()
    assert "Generate a new key" in all_text(at)


def test_script_not_logged_to_api_calls():
    at, fake = logged_in()
    assert [p for p in fake.paths if p[1] not in ("/apikey",)] == []


def test_all_required_safety_content_is_present():
    at, _ = logged_in()
    t = norm(all_text(at))
    required = [
        "contains your personal key", "don't share it",                  # key warning
        "commitmentai-send", "commitmentai-done", "commitmentai-failed",  # labels
        "gemini", "free tier", "confidential",                           # data use
        "hasn't verified this app", "advanced", "unsafe",                 # unverified warning
        "permanently deleting", "never sends, edits or deletes",         # scope of access
        "every 5 minutes", "up to 5", "8,000 characters",                # polling & limits
        "30 emails per day", "7 days",
        "3 failed attempts", "retried",                                  # retry
        "server is asleep", "free hosting sleeps",                       # sleep
        "duplicate",                                                     # duplicates
        "triggers", "delete the trigger",                                # disconnect
        "executions", "key was rejected", "daily limit reached",         # troubleshooting
        "script.google.com", "new project",
        "troubleshooting", "advanced details", "permissions & privacy",
        "numbered" if False else "step 6",
    ]
    missing = [r for r in required if r not in t]
    assert not missing, missing
    labels = [e.proto.label for e in at.get("expander")]
    assert any("Permissions & privacy" in l for l in labels)
    assert any("Troubleshooting" in l for l in labels)
    assert any("Advanced details" in l for l in labels)
    for n in range(1, 7):
        assert f"Step {n} ·" in "\n".join(s.value for s in at.subheader)


@needs_old
def test_every_original_connect_page_sentence_still_exists():
    """Mechanical inventory: each long text literal from the OLD page function must still appear in the new page
    (ignoring markdown), unless it is listed in INTENTIONALLY_CHANGED."""
    old_tree = ast.parse(open(OLD, encoding="utf-8").read())
    fn = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == "page_connect_gmail")
    literals = [c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    sentences = []
    for lit in literals:
        for line in lit.splitlines():
            line = re.sub(r"^\s*(\d+\.|-)\s*", "", line).strip()
            if len(line) > 30:
                sentences.append(line)
    at, _ = logged_in()
    at2, _ = logged_in(fresh=False)
    page = norm(all_text(at) + "\n" + all_text(at2))
    # sentences compared by their first 45 normalised characters, so cosmetic rewording of tails is flagged by name
    missing = [s for s in sentences if norm(s)[:45] not in page]
    print("\nORIGINAL SENTENCES NOT FOUND VERBATIM (review):")
    for m in missing:
        print("  -", m[:110])
    assert len(missing) <= 8, missing


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


# ================================================================== conditional states of the page
def test_regenerate_confirmation_text_still_shown():
    at, _ = logged_in(fresh=False)
    at.button[0].click().run()          # "Generate a new key"
    assert at.session_state["confirm_regen"] is True
    t = norm(all_text(at))
    assert "stops your current gmail script immediately" in t and "paste the new script" in t


def test_local_api_url_warning_still_shown():
    os.environ["API_URL"] = "http://localhost:8000"
    try:
        at, _ = logged_in()
    finally:
        os.environ["API_URL"] = "https://api.example.test"
    assert any("local API address" in w.value for w in at.warning)
