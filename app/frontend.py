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

import os
import time

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

# Used only for the sign-up notice, which is shown BEFORE login (the API reports
# its live limits only to logged-in users, via /usage). Keep in sync with the API
# defaults (or its environment overrides) if you ever change them.
NOTICE_DAILY_LIMIT = 30
NOTICE_RETENTION_DAYS = 7
DEFAULT_MAX_CHARS = 8000

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


@st.cache_data(ttl=20, show_spinner=False)
def check_health():
    try:
        r = requests.get(f"{API_URL}/health", timeout=8)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.RequestException, ValueError):
        return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _clear_session():
    for key in ("token", "userid", "confirm_clear"):
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
- This is a student demo project, provided as-is.
"""


def render_auth():
    st.title("📋 AI Commitment Intelligence")
    st.caption(
        "Paste an email or thread. The system extracts the commitments (who promised what, "
        "to whom, by when), ranks them by urgency, and explains each ranking."
    )
    show_flash()

    health = check_health()
    if health is None:
        st.warning(
            "The server is starting up (free hosting sleeps when idle). "
            "This can take up to a minute. You can still press Log in or Create account: "
            "it will wait for the server to wake up first."
        )
        if st.button("Check again"):
            check_health.clear()
            st.rerun()
    elif health.get("paused"):
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
        st.info("Nothing here yet. Paste an email above and click Process.")
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
    st.caption("Your text is processed by Google's Gemini API (free tier). Please don't submit confidential emails.")

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
# Router
# ---------------------------------------------------------------------------

def render_app():
    with st.sidebar:
        st.markdown(f"Logged in as **{st.session_state.get('userid', '')}**")
        st.radio("Go to", ["Dashboard", "Account"], key="page", label_visibility="collapsed")
        if st.button("Log out"):
            _clear_session()
            flash("info", "You have been logged out.")
            st.rerun()

    if st.session_state.get("page") == "Account":
        page_account()
    else:
        page_dashboard()


def main():
    if st.session_state.get("token"):
        render_app()
    else:
        render_auth()


main()
