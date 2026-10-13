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

import json
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
    for key in ("token", "userid", "confirm_clear", "fresh_key", "confirm_regen"):
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


def page_connect_gmail():
    st.title("📧 Connect Gmail")
    show_flash()

    st.write(
        "Optional. Connect your own Gmail so that emails **you choose** are processed automatically "
        "and their commitments show up on your Dashboard."
    )
    st.info(
        "**How it works and what it can see**\n\n"
        "- You paste a small script into **your own** Google account. It runs there, on a timer.\n"
        "- It only looks at emails you label **CommitmentAI-Send**. Nothing else is read or sent.\n"
        "- This app never receives your Google password or any Google login token. It only receives "
        "the **text of the emails you label** (first 8,000 characters), plus your personal key.\n"
        "- That text goes to Google's Gemini API (free tier: it may be used to improve Google's products "
        "and read by reviewers). **Don't label confidential emails, or other people's private emails.**\n"
        "- The usual limits apply (daily emails, 7-day retention). Results can take up to 5 minutes to appear."
    )

    if any(h in API_URL for h in ("localhost", "127.0.0.1")):
        st.warning("This dashboard is pointed at a local API address, so a script on Google's servers "
                   "could not reach it. (On the live site this is set to the public API URL.)")

    # ---------------- 1. key ----------------
    st.subheader("1. Your personal key")
    try:
        status = api("GET", "/apikey")
    except ApiError as e:
        show_error(e)
        return

    fresh = st.session_state.get("fresh_key")

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

    # ---------------- 2. script ----------------
    st.subheader("2. Your script")
    script = build_script(API_URL, fresh)
    if not fresh:
        st.caption("This copy has a placeholder where your key goes. Generate a key above to get a script "
                   "with your key already inside.")
    st.code(script, language="javascript")
    st.download_button("⬇️ Download as a file (.gs)", data=script, file_name="commitment_ai_gmail.gs",
                       mime="text/plain")

    # ---------------- 3. install ----------------
    st.subheader("3. Install it (about 5 minutes, once)")
    st.markdown(
        """
1. Open [script.google.com](https://script.google.com) while signed in to the Gmail account you want to connect, then click **New project**.
2. Delete the placeholder code, paste the script from step 2, and click **Save**.
3. In the toolbar, choose the function **setup** and click **Run**. Google will ask you to authorize it:
   - You'll see **"Google hasn't verified this app."** That is expected: you're running a script you pasted yourself, not a published app. Click **Advanced**, then **Go to … (unsafe)**, then **Allow**.
   - **Read the permission list on that screen.** Apps Script's Gmail access is broad: Google describes its widest Gmail permission as reading, composing, sending and permanently deleting all your email. This script's code only searches threads you labeled and adds its own labels. It never sends, edits or deletes mail, and you can read every line above.
   - It also asks to connect to an external service (this app) and to run when you're not present (the 5-minute timer).
4. The execution log should say it created three labels (`CommitmentAI-Send`, `-Done`, `-Failed`) and set a timer.
5. In Gmail, apply the label **CommitmentAI-Send** to any email you want processed. (You can also create a Gmail filter that applies it automatically, for example for emails from one person.)
6. Within about 5 minutes it is processed and labeled **CommitmentAI-Done**. Open the **Dashboard** and press **Refresh**: its commitments appear with Source "gmail".
        """
    )

    st.subheader("4. If something looks wrong")
    st.markdown(
        """
- **Nothing appears:** in Apps Script open **Executions** (left sidebar) to see the log. You can also run `processLabeledEmails` by hand.
- **"Your key was rejected":** you generated a newer key, or deleted the account. Generate a new key here and paste the new script.
- **Label `CommitmentAI-Failed`:** the app couldn't use that email (too long, invalid, or it failed three times). It won't be retried.
- **Daily limit reached:** the script waits and tries again automatically; the limit resets at midnight UTC.
- **To stop it:** in Apps Script click the clock icon (**Triggers**) and delete the trigger, or delete the project. Generating a new key here also cuts off the old script immediately.
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
        st.radio("Go to", ["Dashboard", "Connect Gmail", "Account"], key="page", label_visibility="collapsed")
        if st.button("Log out"):
            _clear_session()
            flash("info", "You have been logged out.")
            st.rerun()

    page = st.session_state.get("page")
    if page != "Connect Gmail":
        # A key is shown only on the page that created it; leaving the page discards it.
        st.session_state.pop("fresh_key", None)
        st.session_state.pop("confirm_regen", None)

    if page == "Account":
        page_account()
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
