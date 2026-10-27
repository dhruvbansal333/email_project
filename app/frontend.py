"""
Multi-user extension, Task 6 -- Streamlit dashboard with login / signup.

What a visitor sees:
  * Not logged in : a Log in / Sign up screen (userid + password, no email).
  * Logged in     : Dashboard (paste/upload an email, your ranked commitments,
                    delete my data) and Account (delete my account).

How it works:
  * The login token lives ONLY in Streamlit's per-tab session state. It is never
    put in the URL, a cookie, or a file. Refreshing the page or opening a new
    tab starts a new session, so you log in again (by design: no "remember me").
  * Every call to the API carries that token, and the API only ever returns the
    logged-in user's own data. This file never touches the database.
  * If the token expires (12 h) or the account is deleted, the next call gets a
    401 and you are sent back to the login screen.

Config (environment variable on the dashboard service):
  API_URL   public URL of the API service, e.g. https://ai-commitment-api.onrender.com
The old INGESTION_SECRET variable is no longer used by this file.
"""

import html
import json
import os
import time

import pandas as pd
import requests
import streamlit as st

try:  # older Streamlit versions only have components.html; newer ones prefer st.iframe
    import streamlit.components.v1 as components
except Exception:  # noqa: BLE001
    components = None

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

# Used only for the sign-up notice, which is shown BEFORE login (the API reports
# its live limits only to logged-in users, via /usage). Keep in sync with the API
# defaults (or its environment overrides) if you ever change them.
NOTICE_DAILY_LIMIT = 30
NOTICE_RETENTION_DAYS = 7
NOTICE_MAX_RESULTS = 200
NOTICE_MAX_ACCOUNTS = 15
NOTICE_USAGE_HISTORY_DAYS = 30
NOTICE_LOGIN_MAX_FAILURES = 5
NOTICE_LOGIN_WINDOW_MINUTES = 10
NOTICE_SESSION_HOURS = 12
DEFAULT_MAX_CHARS = 8000

READY_MESSAGE = "Getting your AI assistant ready… This may take a little while on the first visit."

WAKING_MESSAGE = (
    "The server took too long to answer. It runs on free hosting that sleeps when idle, "
    "so the first request can take up to a minute. Please wait a little and try again."
)
ASLEEP_MESSAGE = (
    "The server had gone to sleep (free hosting does that when idle) and has just woken up, "
    "so that request did not go through. Please click the button again."
)

UNSURE_MESSAGE = (
    "The server took too long to answer, so we can't be sure that request went through. "
    "Before trying again, check whether it did (log in again, or press Refresh on the dashboard)."
)

# How long to wait for a sleeping server to wake, and how often to check.
# (Environment overrides exist mainly so the automated tests can run quickly.)
WAKE_MAX_SECONDS = float(os.environ.get("WAKE_MAX_SECONDS", "75"))
WAKE_POLL_SECONDS = float(os.environ.get("WAKE_POLL_SECONDS", "3"))

st.set_page_config(page_title="AI Commitment Intelligence", page_icon="📋", layout="wide")


# ---------------------------------------------------------------------------
# API access
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _detail(resp) -> str:
    try:
        detail = resp.json().get("detail")
    except Exception:  # noqa: BLE001 - body wasn't JSON
        detail = None
    if isinstance(detail, list):     # request-validation errors arrive as a list
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    return detail or f"Unexpected error ({resp.status_code})."


def _is_proxy_error(resp) -> bool:
    """True for a 502/503/504 that did NOT come from our app.

    Our API always attaches a JSON "detail" to its own errors (for example
    "Extraction failed: ..." or "Processing is temporarily paused"). A bare
    502/503/504 means the hosting platform's proxy answered instead, which is
    what happens while a sleeping free instance is still starting up."""
    if resp.status_code not in (502, 503, 504):
        return False
    try:
        body = resp.json()
    except ValueError:
        return True
    return not (isinstance(body, dict) and "detail" in body)


def _wake_server() -> bool:
    """Poll /health (a harmless read) until the API answers, or give up."""
    with st.spinner("The server is waking up (free hosting sleeps when idle). This can take up to a minute..."):
        deadline = time.monotonic() + WAKE_MAX_SECONDS
        while True:
            try:
                r = requests.get(f"{API_URL}/health", timeout=10)
                if r.ok and r.json().get("status") == "ok":
                    return True
            except (requests.exceptions.RequestException, ValueError):
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(WAKE_POLL_SECONDS)


def api(method, path, *, body=None, auth=True, expire_on_401=True, timeout=60):
    """Calls the API. Returns parsed JSON or raises ApiError with a message that is
    safe to show the user. A 401 on an authenticated call means the session is
    over, so it is cleared here (set expire_on_401=False for calls where a 401
    means 'wrong password', not 'session over').

    Cold starts: if the hosting proxy rejects the call because the server is
    asleep, we wake it first. Reads and login are then retried once, because
    repeating them is harmless. Everything else (sign-up, processing, deleting,
    key changes) is NOT retried automatically: the user is told it didn't go
    through, so nothing can ever happen twice."""

    headers = {}
    if auth:
        token = st.session_state.get("token")
        if not token:
            raise ApiError(401, "Please log in.")
        headers["Authorization"] = f"Bearer {token}"

    safe_to_retry = method == "GET" or path == "/login"

    for attempt in (1, 2):
        try:
            resp = requests.request(method, f"{API_URL}{path}", json=body, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ApiError(0, WAKING_MESSAGE)
        except requests.exceptions.ConnectionError:
            resp = None            # nothing is accepting connections: treat like a sleeping server
        except requests.exceptions.RequestException:
            raise ApiError(0, "Cannot reach the server right now. Please try again in a moment.")

        if resp is not None and not _is_proxy_error(resp):
            break

        # 504 = the gateway gave up waiting. The app may already have received (and even
        # finished) the request, so for anything that changes data we must NOT say "it
        # didn't go through" and invite a repeat.
        if resp is not None and resp.status_code == 504 and not safe_to_retry:
            raise ApiError(0, UNSURE_MESSAGE)

        # The server is asleep or still starting.
        if attempt == 1 and _wake_server():
            if safe_to_retry:
                continue
            raise ApiError(0, ASLEEP_MESSAGE)
        raise ApiError(
            0,
            WAKING_MESSAGE if resp is not None
            else "Cannot reach the server right now. Please try again in a moment.",
        )

    if resp.status_code == 401 and auth and expire_on_401:
        _clear_session()
        raise ApiError(401, "Your session has expired. Please log in again.")

    if not resp.ok:
        raise ApiError(resp.status_code, _detail(resp))

    return resp.json()


def _health_once(timeout=8):
    """One uncached call to the API's /health. Returns its JSON, or None if it isn't answering."""
    try:
        r = requests.get(f"{API_URL}/health", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.RequestException, ValueError):
        return None


@st.cache_data(ttl=20, show_spinner=False)
def check_health():
    return _health_once()


def wait_for_api():
    """Poll /health until the API answers or the time budget (WAKE_MAX_SECONDS) runs out.
    Shows live progress. Returns the health dict, or None if it never answered.
    Bounded on purpose: free hosting wakes in roughly 30-60 s but can take longer, and
    nothing here can make it faster."""
    slot = st.empty()
    started = time.monotonic()
    while True:
        waited = int(time.monotonic() - started)
        slot.info(
            f"⏳ {READY_MESSAGE} ({waited}s so far.) Free hosting sleeps when idle; this usually "
            "takes 30-60 seconds and sometimes longer. This page continues by itself when it is ready."
        )
        health = _health_once()
        if health is not None:
            slot.empty()
            check_health.clear()
            return health
        if time.monotonic() - started + WAKE_POLL_SECONDS >= WAKE_MAX_SECONDS:
            slot.empty()
            return None
        time.sleep(WAKE_POLL_SECONDS)


def _retry_wake():
    """Retry button callback: forget that we gave up and drop the cached /health result."""
    st.session_state.pop("api_gave_up", None)
    check_health.clear()


def ensure_api_ready():
    """Login screen: make sure the API is awake before showing the forms.
    The first quick call already wakes a sleeping server; if it doesn't answer yet we wait,
    bounded. Returns the health dict, or None after giving up (with a Retry button shown)."""
    with st.spinner(READY_MESSAGE):
        health = check_health()
    if health is not None:
        st.session_state.pop("api_gave_up", None)
        return health

    if not st.session_state.get("api_gave_up"):
        health = wait_for_api()
        if health is not None:
            return health
        st.session_state["api_gave_up"] = True      # don't re-wait on every click

    st.error(
        f"The server hasn't answered after about {int(WAKE_MAX_SECONDS)} seconds. Free hosting can take "
        "a minute or two to wake up, and sometimes longer, so it may still be starting. "
        "Log in and Sign up appear as soon as it answers. Press Retry to check again."
    )
    # on_click (not st.rerun inside an `if st.button`): Streamlit reruns by itself after the callback, so the
    # Retry button is not drawn again in the pass that follows the click.
    st.button("🔄 Retry", on_click=_retry_wake)
    return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _clear_session():
    for key in ("token", "userid", "confirm_clear", "fresh_key", "confirm_regen", "show_script"):
        st.session_state.pop(key, None)


def _login_success(data: dict):
    st.session_state["token"] = data["token"]
    st.session_state["userid"] = data["userid"]
    st.session_state["page"] = "Dashboard"


def flash(kind: str, text: str):
    """Show a message on the NEXT run (used right before st.rerun())."""
    st.session_state["flash"] = (kind, text)


def show_flash():
    item = st.session_state.pop("flash", None)
    if item:
        getattr(st, item[0])(item[1])


def show_error(e: ApiError):
    """Display an API error; if it ended the session, go back to the login screen."""
    if e.status == 401 and not st.session_state.get("token"):
        flash("warning", e.message)
        st.rerun()
    st.error(e.message)


def fmt_seconds(seconds: int) -> str:
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes = rest // 60
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def show_table(df: pd.DataFrame, **kwargs):
    """Full-width table that works across Streamlit versions."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except Exception:  # noqa: BLE001 - older Streamlit: no width="stretch"
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


# ---------------------------------------------------------------------------
# Not logged in: Log in / Sign up
# ---------------------------------------------------------------------------

SIGNUP_NOTICE = f"""
**Please read before signing up**

- **No email, no password reset.** If you forget your password it cannot be recovered; you would need to create a new account.
- **Your text is sent to Google's Gemini API** to extract commitments. This app uses Google's *free* tier, where Google may use submitted content to improve its products and human reviewers may read it. **Do not submit confidential or private emails, or other people's emails without their permission. Use sample or test emails.**
- Results are kept for **{NOTICE_RETENTION_DAYS} days**, then deleted automatically. You can delete your data or your whole account at any time.
- Fair-use limits: **{NOTICE_DAILY_LIMIT} emails per day**, up to {DEFAULT_MAX_CHARS:,} characters each.
- **Not for use from the EEA, Switzerland or the UK.** Google's terms for the free Gemini tier don't allow apps built on it to be offered to users in those regions. Please don't use this demo from there.
- This is a student demo project, provided as-is.
- The full **Privacy & consent** notice is just below this form.
"""


PRIVACY_LAST_UPDATED = "October 2026"


def privacy_notice_markdown() -> str:
    """The single, complete Privacy & consent notice. Every number comes from the constants above, and
    tests/test_privacy_page.py checks them against the backend's real defaults so the text can't drift."""
    return f"""
*Last updated: {PRIVACY_LAST_UPDATED}. This is a student demo project, provided as-is. It has not had a professional security audit or a legal review.*

### The short version
- **You decide what goes in:** text you paste or upload, or emails you label in Gmail.
- **That text is sent to Google's Gemini API** (free tier) to find commitments. On the free tier Google may use submitted content to improve its products, and human reviewers may read it. **Don't submit confidential emails, or other people's emails without their permission.**
- **We store the extracted commitments, not the email.** They are kept for **{NOTICE_RETENTION_DAYS} days**, then deleted. You can delete them, or your whole account, at any time.
- **No email address and no password reset.** A forgotten password can't be recovered.
- **Not for use from the EEA, Switzerland or the UK** (see "Where you may use this demo").

### What is stored
| Data | How it is stored |
|---|---|
| Userid | As you chose it. |
| Password | Only as a one-way bcrypt hash. The password itself is never stored. |
| Gmail connection key (optional) | Only as a SHA-256 hash. The key is shown to you once and can't be shown again. |
| Extracted commitments | Commitment text, direction, deadline, confidence, sender and recipient names as found in the email, urgency score, explanation, source (dashboard or Gmail) and time. These are pieces of your email, kept as extracted and **not anonymised**, so they can contain names and other personal details. |
| Daily usage counter | How many emails your account processed each day (kept about {NOTICE_USAGE_HISTORY_DAYS} days). |

**Not stored in the database:** the full text of the emails you submit. It is held in memory while it is processed and sent to Gemini. The app's own server logs record timings, counts and warnings, not email text. Our hosting providers keep their own technical logs, which we don't control.

### Who handles your data
| Who | What they receive | Why |
|---|---|---|
| Google (Gemini API) | The text of each email you submit | To extract the commitments |
| Google (Gmail and Apps Script) | Only if you connect Gmail: the script runs inside your own Google account | To read the conversations you label |
| Render | Web traffic to the dashboard and the API | Hosting |
| Neon | The database contents described above | Storage |
| The project owner | Has administrative access to the hosting and database, so could technically read stored results | Running the demo |

### Where you may use this demo
Google's Gemini API terms say that apps offered to users in the European Economic Area, Switzerland or the United Kingdom must use Google's paid service. This demo uses the **free** tier, so it is **not intended for use from those regions**. The app does not detect your location or block anyone; it relies on you.

### Keeping and deleting your data
- Results are kept for **{NOTICE_RETENTION_DAYS} days** (newest **{NOTICE_MAX_RESULTS}** only). Older ones are hidden straight away, and a cleanup that runs while the service is in use (at most once an hour) deletes them permanently.
- **Delete my data** (Dashboard) removes all your stored results immediately.
- **Delete my account** (Account) removes your account, your Gmail key and your results. It asks for your password and can't be undone.
- Text already sent to Google can't be recalled by us. Our database host may also keep short-lived internal backups that we don't control.

### Account security
- Sessions last **{NOTICE_SESSION_HOURS} hours**. Logging out ends your session in this browser. A session token can't be cancelled early on the server; it simply expires.
- After **{NOTICE_LOGIN_MAX_FAILURES} wrong passwords** for a userid within **{NOTICE_LOGIN_WINDOW_MINUTES} minutes**, logging in to it is blocked for up to {NOTICE_LOGIN_WINDOW_MINUTES} minutes. (This counter is kept in memory and resets when the server restarts.)
- Login errors don't reveal whether a userid exists.
- There is **no email and no password reset**. If you forget your password, create a new account; the old data can't be recovered.

### Connecting Gmail (optional)
- You paste a script into your **own** Google account. It only looks at conversations you label **CommitmentAI-Send**, and sends the body text of the newest message in each (first {DEFAULT_MAX_CHARS:,} characters) together with your personal key. This app never receives your Google password or a Google login token.
- Anyone who gets your script can use the key inside it to reach your commitment data in this app (not your Gmail or your login password). Generating a new key stops the old script immediately.
- You can stop at any time by deleting the script's trigger in Apps Script.

### Limits
Up to **{NOTICE_DAILY_LIMIT} emails per day** per account, **{DEFAULT_MAX_CHARS:,} characters** each, and **{NOTICE_MAX_RESULTS} stored results**. This demo accepts at most **{NOTICE_MAX_ACCOUNTS} accounts**. The owner can pause new accounts and processing; you can still log in to view or delete your data.

### Accuracy and responsibility
Extraction is automated and can miss or misread commitments, so check anything important yourself. If you submit other people's emails, you are responsible for having their permission. The demo is provided as-is and may be changed, paused or removed.

### Your consent
Ticking the box when you create an account confirms that you have read this notice. You can withdraw at any time by deleting your account.
"""


def page_privacy():
    st.title("🔒 Privacy & consent")
    st.markdown(privacy_notice_markdown())


def render_auth():
    st.title("📋 AI Commitment Intelligence")
    st.caption(
        "Paste an email or thread. The system extracts the commitments (who promised what, "
        "to whom, by when), ranks them by urgency, and explains each ranking."
    )
    show_flash()

    health = ensure_api_ready()
    if health is None:
        # The server isn't answering yet: show only the message and the Retry button.
        # Log in / Sign up are offered once the API has actually answered.
        return
    if health.get("paused"):
        st.warning(
            "The demo is temporarily paused: new accounts and processing are unavailable. "
            "You can still log in to view or delete your data."
        )

    login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

    with login_tab:
        with st.form("login_form"):
            userid = st.text_input("Userid")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            if not userid.strip() or not password:
                st.error("Please enter your userid and password.")
            else:
                with st.spinner("Logging in..."):
                    try:
                        data = api("POST", "/login", body={"userid": userid, "password": password},
                                   auth=False, timeout=90)
                    except ApiError as e:
                        st.error(e.message)
                    else:
                        _login_success(data)
                        st.rerun()

    with signup_tab:
        with st.form("signup_form"):
            new_userid = st.text_input(
                "Choose a userid", help="3-32 characters: letters, numbers or underscore. Not case-sensitive.")
            new_password = st.text_input("Choose a password", type="password", help="At least 8 characters.")
            confirm = st.text_input("Confirm password", type="password")
            st.info(SIGNUP_NOTICE)
            agreed = st.checkbox("I have read and understand the above")
            submitted = st.form_submit_button("Create account")
        if submitted:
            if not new_userid.strip() or not new_password:
                st.error("Please choose a userid and a password.")
            elif new_password != confirm:
                st.error("The two passwords don't match.")
            elif not agreed:
                st.error("Please tick the box to confirm you've read the notice.")
            else:
                with st.spinner("Creating your account..."):
                    try:
                        data = api("POST", "/signup", body={"userid": new_userid, "password": new_password},
                                   auth=False, timeout=90)
                    except ApiError as e:
                        st.error(e.message)
                    else:
                        _login_success(data)
                        flash("success", f"Welcome, {data['userid']}! Your account is ready.")
                        st.rerun()

    with st.expander("📄 Read the full Privacy & consent notice"):
        st.markdown(privacy_notice_markdown())


# ---------------------------------------------------------------------------
# Logged in: Dashboard
# ---------------------------------------------------------------------------

COLUMNS = {
    "urgency_score": "Urgency",
    "commitment_text": "Commitment",
    "direction": "Direction",
    "deadline_text": "Deadline",
    "confidence": "Confidence",
    "sender": "From",
    "recipient": "To",
    "_source": "Source",
    "_processed_at": "Processed (UTC)",
    "explanation": "Why this rank",
}


def page_dashboard():
    st.title("📋 Dashboard")

    usage = None
    try:
        usage = api("GET", "/usage")
    except ApiError as e:
        show_error(e)

    max_chars = usage["max_text_chars"] if usage else DEFAULT_MAX_CHARS
    paused = bool(usage and usage.get("paused"))
    at_limit = bool(usage and usage["used_today"] >= usage["daily_limit"])

    if usage:
        used, limit = usage["used_today"], usage["daily_limit"]
        st.progress(
            min(used / limit, 1.0),
            text=f"{used} of {limit} emails used today. Resets in {fmt_seconds(usage['resets_in_seconds'])} (midnight UTC).",
        )
    if paused:
        st.warning("Processing is temporarily paused. You can still view and delete your results.")
    elif at_limit:
        st.warning("You've used today's emails. You can still view your results; the limit resets at midnight UTC.")

    show_flash()

    col_input, col_actions = st.columns([3, 1])
    with col_input:
        pasted = st.text_area(
            "Paste email or thread text",
            height=200,
            placeholder="Hi Priya, I'll send you the revised contract by Friday afternoon. "
                        "Also, can you review the attached budget by end of day tomorrow?",
        )
        uploaded = st.file_uploader("...or upload a .txt / .eml file instead", type=["txt", "eml"])
        text = pasted
        if uploaded is not None:
            text = uploaded.getvalue().decode("utf-8", errors="replace")
            st.text_area("File contents (loaded)", value=text, height=150, disabled=True)

        too_long = len(text) > max_chars
        st.caption(f"{len(text):,} / {max_chars:,} characters")
        if too_long:
            st.error(f"This text is {len(text):,} characters; the limit is {max_chars:,}. Please shorten it.")

    with col_actions:
        st.write("")
        st.write("")
        can_process = bool(text.strip()) and not too_long and not paused and not at_limit
        process_clicked = st.button("🔍 Process", type="primary", disabled=not can_process)

    if process_clicked:
        with st.spinner("Extracting and ranking commitments..."):
            try:
                result = api("POST", "/process", body={"text": text, "source": "dashboard"}, timeout=90)
            except ApiError as e:
                show_error(e)
            else:
                n = len(result.get("ranked_commitments", []))
                if n:
                    flash("success", f"Found {n} commitment(s).")
                else:
                    flash("info", "No commitments found in this text.")
                st.rerun()      # refresh the usage bar and the table below

    st.divider()
    st.subheader("Your commitments")

    col_a, col_b = st.columns([1, 3])
    with col_a:
        st.button("🔄 Refresh")           # any click re-runs the page, which re-reads your results
    with col_b:
        hide_low = st.checkbox("Hide low-confidence items", value=True)

    results = []
    try:
        results = api("GET", "/results")["results"]
    except ApiError as e:
        show_error(e)

    if hide_low:
        results = [r for r in results if r.get("confidence") != "low"]

    if not results:
        st.info("Nothing here yet. Paste an email above and click Process, "
                "or connect Gmail (sidebar) to process emails you label automatically.")
    else:
        df = pd.DataFrame(results)
        df["_processed_at"] = df["_processed_at"].astype(str).str[:16].str.replace("T", " ")
        cols = [c for c in COLUMNS if c in df.columns]
        show_table(
            df[cols].rename(columns=COLUMNS),
            column_config={
                "Urgency": st.column_config.NumberColumn("Urgency", format="%.1f"),
                "Commitment": st.column_config.TextColumn("Commitment", width="large"),
                "Why this rank": st.column_config.TextColumn("Why this rank", width="large"),
            },
        )
        st.caption(f"{len(df)} commitment(s). Results are deleted automatically after {usage['retention_days'] if usage else NOTICE_RETENTION_DAYS} days.")

    # ---- Delete my data (two-step confirm) ----
    st.divider()
    if st.session_state.get("confirm_clear"):
        st.warning("Delete ALL your stored results? This can't be undone.")
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Yes, delete everything", type="primary"):
            try:
                out = api("POST", "/results/clear")
            except ApiError as e:
                show_error(e)
            else:
                st.session_state["confirm_clear"] = False
                flash("success", f"Deleted {out.get('deleted', 0)} result(s).")
                st.rerun()
        if c2.button("Cancel"):
            st.session_state["confirm_clear"] = False
            st.rerun()
    else:
        if st.button("🗑️ Delete my data"):
            st.session_state["confirm_clear"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Logged in: Account
# ---------------------------------------------------------------------------

def page_account():
    st.title("👤 Account")
    show_flash()

    try:
        me = api("GET", "/me")
        usage = api("GET", "/usage")
    except ApiError as e:
        show_error(e)
        return

    st.write(f"**Userid:** {me['userid']}")
    st.write(f"**Created:** {str(me['created_at'])[:16].replace('T', ' ')} UTC")
    st.write(
        f"**Limits:** {usage['daily_limit']} emails per day, {usage['max_text_chars']:,} characters each. "
        f"Results are kept for {usage['retention_days']} days (newest {usage['max_results']} only), then deleted automatically."
    )
    st.caption("Your text is processed by Google's Gemini API (free tier). Please don't submit confidential emails. "
               "Full details: **Privacy & consent** in the sidebar.")

    st.divider()
    st.subheader("Delete my account")
    st.write(
        "This permanently deletes your account and every result stored for it. "
        "It cannot be undone, and there is no way to recover it."
    )
    with st.form("delete_account_form"):
        password = st.text_input("Enter your password to confirm", type="password")
        sure = st.checkbox("I understand this is permanent")
        submitted = st.form_submit_button("Delete my account")
    if submitted:
        if not password:
            st.error("Please enter your password.")
        elif not sure:
            st.error("Please tick the box to confirm.")
        else:
            try:
                api("POST", "/account/delete", body={"password": password}, expire_on_401=False)
            except ApiError as e:
                st.error(e.message)
            else:
                _clear_session()
                flash("success", "Your account and all its data have been deleted.")
                st.rerun()


# ---------------------------------------------------------------------------
# Logged in: Connect Gmail
# ---------------------------------------------------------------------------

SCRIPT_TEMPLATE = r"""/**
 * AI Commitment Intelligence - Gmail connector (generated for your account)
 *
 * KEEP THE KEY BELOW SECRET. Treat it like a password: don't share this script
 * or post it anywhere. If it leaks, generate a new key on the Connect Gmail page
 * (the old key stops working immediately).
 *
 * What it does:
 *  - Every 5 minutes it looks ONLY at Gmail threads you have labeled "CommitmentAI-Send".
 *  - It sends the text of the newest message in each (first 8,000 characters) to the
 *    app. The app extracts and ranks the commitments and shows them on your dashboard.
 *  - Then it adds the label "CommitmentAI-Done" so that thread is never sent twice.
 *  - If an email can never be processed (too long to read, rejected, or it failed 3
 *    times) it gets "CommitmentAI-Failed" and is left alone.
 *  It never sends, edits or deletes any email. It only adds its own three labels.
 *
 * Setup: pick the function "setup" in the toolbar, click Run, and approve the permissions.
 */

const API_URL = __API_URL__;
const API_KEY = __API_KEY__;

const SEND_LABEL = "CommitmentAI-Send";
const DONE_LABEL = "CommitmentAI-Done";
const FAILED_LABEL = "CommitmentAI-Failed";
const HANDLER = "processLabeledEmails";
const TRIGGER_MINUTES = 5;
const MAX_THREADS_PER_RUN = 5;
const MAX_CHARS = 8000;
const MAX_ATTEMPTS = 3;

// Run this ONCE: creates the labels and the 5-minute timer. Safe to run again.
function setup() {
  [SEND_LABEL, DONE_LABEL, FAILED_LABEL].forEach(function (name) {
    if (!GmailApp.getUserLabelByName(name)) {
      GmailApp.createLabel(name);
      Logger.log("Created label: " + name);
    }
  });
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === HANDLER) {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger(HANDLER).timeBased().everyMinutes(TRIGGER_MINUTES).create();
  Logger.log("Ready. Label any email '" + SEND_LABEL + "' and it will be picked up within " +
             TRIGGER_MINUTES + " minutes.");
}

// Runs automatically every 5 minutes (you can also run it by hand to test).
function processLabeledEmails() {
  if (!API_KEY || API_KEY.indexOf("cai_") !== 0) {
    Logger.log("No API key set. Generate one on the app's Connect Gmail page and paste it into API_KEY.");
    return;
  }
  const doneLabel = GmailApp.getUserLabelByName(DONE_LABEL);
  const failedLabel = GmailApp.getUserLabelByName(FAILED_LABEL);
  if (!GmailApp.getUserLabelByName(SEND_LABEL) || !doneLabel || !failedLabel) {
    Logger.log("Labels are missing. Run the function 'setup' once first.");
    return;
  }

  // Never let two runs overlap (the timer firing while you press Run, or a slow run
  // outlasting 5 minutes): that could send the same email twice.
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    Logger.log("Another run is still in progress; skipping this one.");
    return;
  }
  try {
    processThreads_(doneLabel, failedLabel);
  } finally {
    lock.releaseLock();
  }
}

// The actual work. Only ever called while holding the lock.
function processThreads_(doneLabel, failedLabel) {
  const props = PropertiesService.getScriptProperties();
  const query = "label:" + SEND_LABEL + " -label:" + DONE_LABEL + " -label:" + FAILED_LABEL;
  const threads = GmailApp.search(query, 0, MAX_THREADS_PER_RUN);
  Logger.log("Found " + threads.length + " labeled email thread(s) to process.");

  for (let i = 0; i < threads.length; i++) {
    const thread = threads[i];
    const id = thread.getId();
    const attemptsKey = "attempts_" + id;
    const messages = thread.getMessages();
    const text = String(messages[messages.length - 1].getPlainBody() || "").trim().substring(0, MAX_CHARS);

    if (!text) {
      thread.addLabel(doneLabel);          // nothing to read in it
      Logger.log("Thread " + id + ": empty, marked done.");
      continue;
    }

    const result = callApi_(text);
    const outcome = classify_(result);

    if (outcome === "ok") {
      thread.addLabel(doneLabel);
      props.deleteProperty(attemptsKey);
      Logger.log("Thread " + id + ": processed.");
    } else if (outcome === "fail") {
      thread.addLabel(failedLabel);        // this email can never work; don't retry it
      props.deleteProperty(attemptsKey);
      Logger.log("Thread " + id + ": rejected by the app (" + result.code + "), marked failed. " + detail_(result));
    } else if (outcome === "attempt") {
      const attempts = Number(props.getProperty(attemptsKey) || 0) + 1;
      if (attempts >= MAX_ATTEMPTS) {
        thread.addLabel(failedLabel);      // keeps one bad email from using your daily quota forever
        props.deleteProperty(attemptsKey);
        Logger.log("Thread " + id + ": failed " + attempts + " times, marked failed.");
      } else {
        props.setProperty(attemptsKey, String(attempts));
        Logger.log("Thread " + id + ": attempt " + attempts + " of " + MAX_ATTEMPTS + " failed; will retry. " + detail_(result));
      }
    } else {
      // "stop": a problem that affects every email (server asleep, limit reached, bad key...).
      // Leave everything unlabeled and try again at the next run.
      Logger.log("Stopping this run (code " + result.code + "). " + detail_(result) +
                 (result.code === 401 ? " -> Your key was rejected: generate a new one and paste it into API_KEY." : ""));
      break;
    }
  }
}

function callApi_(text) {
  try {
    const response = UrlFetchApp.fetch(API_URL, {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ text: text, source: "gmail" }),
      muteHttpExceptions: true
    });
    return { code: response.getResponseCode(), body: response.getContentText() };
  } catch (err) {
    return { code: 0, body: "" };          // network error or timeout
  }
}

// Decide what to do with the app's answer.
//  ok      - done
//  fail    - this particular email will never work (empty/too long/invalid): mark failed
//  attempt - the AI step failed for this email: count it, retry, give up after MAX_ATTEMPTS
//  stop    - not this email's fault: wait for the next run (nothing is labeled or counted)
function classify_(r) {
  if (r.code === 200) return "ok";
  if (r.code === 0) return "stop";
  let hasDetail = false;
  try { hasDetail = !!JSON.parse(r.body).detail; } catch (e) {}
  if (!hasDetail) return "stop";           // not an answer from the app (e.g. the server is waking up)
  if (r.code === 400 || r.code === 413 || r.code === 422) return "fail";
  if (r.code >= 500 && r.code !== 503) return "attempt";
  return "stop";                           // 401 bad key, 429 limit reached, 503 paused, anything unexpected
}

function detail_(r) {
  try { return String(JSON.parse(r.body).detail || ""); } catch (e) { return ""; }
}
"""


def build_script(api_url: str, key) -> str:
    """The Apps Script the user pastes, with the endpoint and (if just generated) their key."""
    endpoint = f"{api_url.rstrip('/')}/process"
    return (
        SCRIPT_TEMPLATE
        .replace("__API_URL__", json.dumps(endpoint))
        .replace("__API_KEY__", json.dumps(key or "PASTE_YOUR_KEY_HERE"))
    )


def copy_button_html(text: str, label: str = "Copy setup script") -> str:
    """A small self-contained HTML page: one button that copies `text` to the clipboard and says
    whether it worked. It runs only in the user's browser; nothing is sent anywhere.
    (`</` is escaped so a script containing "</script>" cannot break out of the page.)"""
    payload = json.dumps(text).replace("</", "<\\/")
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
  button {{ font: inherit; font-weight: 600; padding: .65rem 1.3rem; border-radius: .5rem; border: 0;
           background: #ff4b4b; color: #fff; cursor: pointer; }}
  button:hover {{ filter: brightness(.92); }}
  #m {{ margin-top: .6rem; font-size: .92rem; line-height: 1.35; }}
  .ok {{ color: #1a7f37; }} .bad {{ color: #c62828; }}
  @media (prefers-color-scheme: dark) {{ .ok {{ color: #56d364; }} .bad {{ color: #ff7b72; }} }}
</style></head>
<body>
<button id="b" type="button">📋 {html.escape(label)}</button>
<div id="m" role="status" aria-live="polite"></div>
<script>
  const TEXT = {payload};
  const msg = document.getElementById("m");
  function ok() {{
    msg.className = "ok";
    msg.textContent = "✅ Copied! Now paste it into Google Apps Script (step 3).";
  }}
  function fail() {{
    msg.className = "bad";
    msg.textContent = "⚠️ Couldn't copy automatically. Click “View script code” below and use the copy icon, " +
                      "or use the download button.";
  }}
  function legacyCopy() {{
    try {{
      const t = document.createElement("textarea");
      t.value = TEXT; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.focus(); t.select();
      const done = document.execCommand("copy");
      document.body.removeChild(t);
      return !!done;
    }} catch (e) {{ return false; }}
  }}
  document.getElementById("b").addEventListener("click", function () {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(TEXT).then(ok, function () {{ legacyCopy() ? ok() : fail(); }});
    }} else {{
      legacyCopy() ? ok() : fail();
    }}
  }});
</script>
</body></html>"""


def embed_html(page_html: str, height: int):
    """Show a small trusted HTML page. Newer Streamlit deprecates components.html in favour of st.iframe,
    so use st.iframe when this version has it and fall back to components.html on older versions."""
    if hasattr(st, "iframe"):
        st.iframe(page_html, height=height)
    else:
        components.html(page_html, height=height)


PRIVACY_TEXT = (
    "**How it works and what it can see**\n\n"
    "- You paste a small script into **your own** Google account. It runs there, on a timer.\n"
    "- It only looks at emails you label **CommitmentAI-Send**. Nothing else is read or sent.\n"
    "- This app never receives your Google password or any Google login token. It only receives "
    "the **text of the emails you label** (first 8,000 characters), plus your personal key.\n"
    "- That text goes to Google's Gemini API (free tier: it may be used to improve Google's products "
    "and read by reviewers). **Don't label confidential emails, or other people's private emails.**\n"
    "- The usual limits apply (daily emails, 7-day retention). Results can take up to 5 minutes to appear.\n"
    "- Full details, including where this demo may be used, are in **Privacy & consent** (sidebar)."
)


def page_connect_gmail():
    st.title("📧 Connect Gmail")
    show_flash()

    st.write(
        "Optional. Connect your own Gmail so that emails **you choose** are processed automatically "
        "and their commitments show up on your Dashboard."
    )
    st.caption(
        "⏱️ One-time setup, about 5 minutes, 6 short steps. "
        "🔒 Only emails **you** label are processed, and their text goes to Google's free Gemini API, "
        "so don't label confidential emails. Details are in *Permissions & privacy* just below."
    )
    with st.expander("🔒 Permissions & privacy: what this can see"):
        st.info(PRIVACY_TEXT)

    if any(h in API_URL for h in ("localhost", "127.0.0.1")):
        st.warning("This dashboard is pointed at a local API address, so a script on Google's servers "
                   "could not reach it. (On the live site this is set to the public API URL.)")

    # ---------------- Step 1: key ----------------
    try:
        status = api("GET", "/apikey")
    except ApiError as e:
        st.subheader("Step 1 · Create your personal connection key")
        show_error(e)
        return

    fresh = st.session_state.get("fresh_key")

    with st.container(border=True):
        st.subheader("Step 1 · Create your personal connection key")
        st.caption(
            "This key is like a private password just for your Gmail script. It lets the script prove to this app "
            "that the emails are yours. It is not your login password and is never made from it."
        )
        if fresh:
            st.success("Your new key is below. **It is shown only now and can't be recovered**, so the script "
                       "in step 2 already contains it. Copy the script before you leave this page.")
            st.code(fresh, language=None)
            if st.button("I've copied the script, hide the key"):
                st.session_state.pop("fresh_key", None)
                st.rerun()
        else:
            if status["has_key"]:
                st.write(
                    f"You already have a key (created {str(status['created_at'])[:16].replace('T', ' ')} UTC). "
                    "For your security only a scrambled version is stored, so it can't be shown again."
                )
                if st.session_state.get("confirm_regen"):
                    st.warning("Generating a new key **stops your current Gmail script immediately** until you "
                               "paste the new script. Continue?")
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("Yes, generate a new key", type="primary"):
                        _generate_key()
                    if c2.button("Cancel"):
                        st.session_state["confirm_regen"] = False
                        st.rerun()
                elif st.button("🔑 Generate a new key"):
                    st.session_state["confirm_regen"] = True
                    st.rerun()
            else:
                st.write("You don't have a key yet.")
                if st.button("🔑 Generate my Gmail key", type="primary"):
                    _generate_key()

    # ---------------- Step 2: script ----------------
    script = build_script(API_URL, fresh)
    with st.container(border=True):
        st.subheader("Step 2 · Copy your setup script")
        if not fresh:
            st.caption("This copy has a placeholder where your key goes. Generate a key above to get a script "
                       "with your key already inside.")
        st.warning(
            "🔑 **This script contains your personal key. Don't share it, post it online or commit it to GitHub.** "
            "Anyone who can see the script could use your key to reach your commitment data in this app "
            "(not your Gmail or your login password). If it ever leaks, generate a new key here: "
            "the old one stops working immediately."
        )
        embed_html(
            copy_button_html(script, "Copy setup script" if fresh else "Copy script template (key not included)"),
            height=95,
        )
        show_code = st.session_state.get("show_script", False)
        if st.button("Hide script code" if show_code else "View script code", key="toggle_script"):
            st.session_state["show_script"] = not show_code
            st.rerun()
        if show_code:
            st.code(script, language="javascript")
        st.download_button("⬇️ Download as a file (.gs)", data=script, file_name="commitment_ai_gmail.gs",
                           mime="text/plain")

    # ---------------- Step 3: open Apps Script ----------------
    with st.container(border=True):
        st.subheader("Step 3 · Open Google Apps Script and paste the script")
        st.markdown(
            """
1. Open [script.google.com](https://script.google.com) while signed in to the Gmail account you want to connect, then click **New project**.
2. Delete the placeholder code, paste the script from step 2, and click **Save**.
            """
        )

    # ---------------- Step 4: run setup + permissions ----------------
    with st.container(border=True):
        st.subheader("Step 4 · Run setup and approve permissions")
        st.caption("Google asks for permission because the script runs inside your Google account. "
                   "You approve it once; it is your own script, so you can read every line.")
        st.markdown(
            """
1. In the toolbar, choose the function **setup** and click **Run**. Google will ask you to authorize it:
   - You'll see **"Google hasn't verified this app."** That is expected: you're running a script you pasted yourself, not a published app. Click **Advanced**, then **Go to … (unsafe)**, then **Allow**.
   - **Read the permission list on that screen.** Apps Script's Gmail access is broad: Google describes its widest Gmail permission as reading, composing, sending and permanently deleting all your email. This script's code only searches threads you labeled and adds its own labels. It never sends, edits or deletes mail, and you can read every line above.
   - It also asks to connect to an external service (this app) and to run when you're not present (the 5-minute timer).
2. The execution log should say it created three labels (`CommitmentAI-Send`, `-Done`, `-Failed`) and set a timer.
            """
        )

    # ---------------- Step 5: label emails ----------------
    with st.container(border=True):
        st.subheader("Step 5 · Label the emails you want processed")
        st.markdown(
            """
In Gmail, apply the label **CommitmentAI-Send** to any email you want processed. (You can also create a Gmail filter that applies it automatically, for example for emails from one person.)
            """
        )
        render_filter_help()

    # ---------------- Step 6: test ----------------
    with st.container(border=True):
        st.subheader("Step 6 · Test your connection")
        st.markdown(
            """
Within about 5 minutes it is processed and labeled **CommitmentAI-Done**. Open the **Dashboard** and press **Refresh**: its commitments appear with Source "gmail".

- **CommitmentAI-Done** means the email was processed.
- **CommitmentAI-Failed** means the app couldn't use that email, and it won't be retried (see *Troubleshooting*).
            """
        )

    # ---------------- expandable detail ----------------
    with st.expander("🛠️ Troubleshooting: if something looks wrong"):
        st.markdown(
            """
- **Nothing appears:** in Apps Script open **Executions** (left sidebar) to see the log. You can also run `processLabeledEmails` by hand.
- **"Your key was rejected":** you generated a newer key, or deleted the account. Generate a new key here and paste the new script.
- **Label `CommitmentAI-Failed`:** the app couldn't use that email (too long, invalid, or it failed three times). It won't be retried.
- **Daily limit reached:** the script waits and tries again automatically; the limit resets at midnight UTC.
- **To stop it:** in Apps Script click the clock icon (**Triggers**) and delete the trigger, or delete the project. Generating a new key here also cuts off the old script immediately.
            """
        )

    with st.expander("⚙️ Advanced details: limits, retries and known limitations"):
        st.markdown(
            """
- **How often:** a timer runs the script every **5 minutes**. Each run handles up to **5** labeled conversations, so results can take a few minutes to appear.
- **What it reads:** only conversations labeled **CommitmentAI-Send** that are not yet labeled Done or Failed. It searches by label and adds its own labels. It does not send, edit or delete mail.
- **What is sent:** the text of each labeled email (first **8,000 characters**) plus your personal key, over HTTPS to this app, which passes the text to Google's Gemini API (free tier).
- **Limits:** about **30 emails per day** per account (the daily count resets at midnight UTC) and results are deleted after **7 days**.
- **Retries:** if the server is asleep or the network fails, the email stays labeled Send and is tried again on the next run. After **3 failed attempts** on the same email it is labeled **CommitmentAI-Failed** and not retried.
- **Free hosting sleeps:** the very first run after a long idle period may fail and simply be retried five minutes later.
- **Possible duplicates:** if a network timeout happens after the app already processed an email, the retry can rarely create a duplicate result. Removing **CommitmentAI-Done** from a conversation to resend it can also create duplicates.
- **Two runs never overlap:** the script uses a lock so a slow run isn't started twice.
- **Stopping:** delete the trigger (clock icon in Apps Script) or the project. Generating a new key here immediately stops any older script.
            """
        )


# Example Gmail searches shown on the Connect Gmail page. Kept as data so they can be sanity-checked.
GMAIL_QUERY_EXAMPLES = [
    ("Promises people make", '("I will" OR "I\'ll" OR "will get back to you" OR "will follow up")'),
    ("Deadlines in the email text", '(deadline OR "due date" OR "by EOD" OR "end of day" OR "by Friday" OR ASAP)'),
    ("Deadlines in the subject line", 'subject:(deadline OR "action required" OR "please confirm")'),
    ("One specific sender", "from:manager@example.com"),
    ("A few specific senders", "from:(alice@example.com OR bob@example.com)"),
    ("Everyone at one company", "from:@example.com"),
    ("Narrow and safer: one sender AND a keyword", 'from:manager@example.com ("I will" OR "I\'ll" OR deadline)'),
    ("Skip promotional noise (add to any search)", "-category:promotions -category:social -from:noreply"),
    ("Only recent mail (handy while testing)", "from:manager@example.com newer_than:7d"),
]


def render_filter_help():
    st.subheader("Optional: label emails automatically with a Gmail filter")
    st.caption(
        "Instead of labeling each email by hand, a Gmail filter can apply **CommitmentAI-Send** for you. "
        "Filters are created in Gmail on a computer; once made, they also work for mail you read on your phone."
    )
    with st.expander("Show me how (beginner-friendly)"):
        t_create, t_ideas, t_test, t_fix = st.tabs(
            ["1. Create the filter", "2. Search ideas", "3. Test it", "4. If it doesn't work"]
        )

        with t_create:
            st.markdown(
                """
**Before you start:** run **setup** once (step 3 above), so the label `CommitmentAI-Send` exists.

1. Open Gmail **on a computer**.
2. At the right end of the search box at the top, click the **Show search options** icon (it looks like little sliders).
3. Fill in what should match: **From** (an email address), **Subject** (words) or **Has the words** (anything in the email). Pick ideas from the **Search ideas** tab.
4. *(Recommended)* Click **Search** first to preview which emails match. Then open **Show search options** again; your criteria are still there.
5. Click **Create filter** at the bottom of the box.
6. Tick **Apply the label**, open **Choose label**, and pick **CommitmentAI-Send**.
7. *(Optional)* Tick **Also apply filter to matching conversations** to label mail you already have. Check first how many that is: you can process **30 emails a day**, and every labeled email is sent to Google's Gemini API.
8. Click **Create filter**.

From now on, matching **new** emails get the label automatically, and the script picks them up within about 5 minutes.

**Shortcut:** tick an email in your inbox, click **More** (three dots), choose **Filter messages like these**, then continue from step 5.
**Good to know:** a reply to a filtered email is only labeled if the reply also matches the same search.
                """
            )

        with t_ideas:
            st.markdown(
                "Copy one into Gmail's search box (or the **Has the words** / **From** fields). "
                "Replace the example addresses with real ones."
            )
            for title, query in GMAIL_QUERY_EXAMPLES:
                st.markdown(f"**{title}**")
                st.code(query, language=None)
            st.markdown(
                """
**Reading these:** write **OR** in capitals; quotes mean an exact phrase; a minus sign excludes; brackets group things together; Gmail searches aren't case-sensitive.

⚠️ **Keep it narrow.** A broad keyword filter can label a lot of mail. Every labeled email is sent to Google's free Gemini API (don't use it on confidential senders) and counts toward your 30 a day. A specific sender, optionally combined with a keyword, is the safest choice.
                """
            )

        with t_test:
            st.markdown(
                """
1. **Test the search first.** Paste your query into Gmail's search box and press Enter. The emails you see are exactly what the filter would label. Too many or too few? Adjust it *before* creating the filter.
2. Create the filter (first tab).
3. **Send a test email that matches.** From a different account is best; an email you send to yourself may also work.
4. Within seconds it should show the label **CommitmentAI-Send** (you'll see it on the email and in the left sidebar).
5. Within about 5 minutes the script adds **CommitmentAI-Done** (the Send label stays).
6. Open the **Dashboard** and press **Refresh**: its commitments appear with Source "gmail".
7. Also check the opposite: an email that should *not* match stays unlabeled.

**Labeling one email by hand:** open it, click the **Labels** icon (a tag) in the toolbar, tick **CommitmentAI-Send**, click **Apply**. On the phone app: three dots, **Change labels**.
                """
            )

        with t_fix:
            st.markdown(
                """
**The email didn't get the label**
- Does your search find it? Paste the query into Gmail's search box. If not, loosen it.
- Filters only act on **new** mail. For older mail, tick *Also apply filter to matching conversations* when creating the filter, or label it by hand.
- The label must be spelled exactly `CommitmentAI-Send`. A similar one you made yourself is ignored. Run **setup** to create the right one.
- Ended up in Spam? Edit the filter and tick **Never send it to Spam**.
- A reply is only labeled if it also matches the filter's search.

**It has the label, but nothing appears on the dashboard**
- Wait up to 5 minutes, then press **Refresh**.
- In Apps Script open **Executions** and look for errors.
- It was labeled **CommitmentAI-Failed**: the app couldn't use that email (too long, rejected, or it failed 3 times). It won't be retried.
- Today's 30 emails are used up: the script waits and the limit resets at midnight UTC.
- "Key was rejected": you generated a newer key. Paste the newer script.

**Too many emails are being labeled**
- In Gmail click **Settings** (gear), **See all settings**, **Filters and Blocked Addresses**, then **Edit** or **Delete**. Removing a filter doesn't remove labels already applied; remove those by hand.
- Each conversation is sent **once**. To send it again, remove **CommitmentAI-Done** from it (this can create duplicate results).
                """
            )


def _generate_key():
    try:
        data = api("POST", "/apikey")
    except ApiError as e:
        show_error(e)
        return
    st.session_state["fresh_key"] = data["api_key"]
    st.session_state["confirm_regen"] = False
    st.rerun()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def render_app():
    with st.sidebar:
        st.markdown(f"Logged in as **{st.session_state.get('userid', '')}**")
        st.radio("Go to", ["Dashboard", "Connect Gmail", "Account", "Privacy & consent"], key="page",
                 label_visibility="collapsed")
        if st.button("Log out"):
            _clear_session()
            flash("info", "You have been logged out.")
            st.rerun()

    page = st.session_state.get("page")
    if page != "Connect Gmail":
        # A key is shown only on the page that created it; leaving the page discards it.
        st.session_state.pop("fresh_key", None)
        st.session_state.pop("confirm_regen", None)
        st.session_state.pop("show_script", None)

    if page == "Account":
        page_account()
    elif page == "Privacy & consent":
        page_privacy()
    elif page == "Connect Gmail":
        page_connect_gmail()
    else:
        page_dashboard()


def main():
    if st.session_state.get("token"):
        render_app()
    else:
        render_auth()


main()
