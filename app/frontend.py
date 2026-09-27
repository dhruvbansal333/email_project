"""
Phase 7, Step 7.3 — Streamlit demo dashboard.

(Updated: Phase 8.5 — sends X-Ingestion-Key header on every call, and
now reads/clears results via the API's shared server-side store
(GET /results, POST /results/clear) instead of a local JSON file.

Why the change: once the API and dashboard became two separate Render
services (Phase 8.5 fix for the 405 issue), a local file on the
dashboard's own disk could never see commitments that Gmail ingestion
sent straight to the API. The API is now the single shared source of
truth for both callers.)

A paste/upload UI that calls the /process endpoint and displays
ranked, explained commitments in a table -- from both manual paste
and, if Phase 8.5 Gmail ingestion is running, automatically-ingested
email too.

Run (with the FastAPI server already running separately):
    pip install streamlit requests pandas
    streamlit run app/frontend.py
"""

import os

import pandas as pd
import requests
import streamlit as st

# Configurable: local (same container) or a separate deployed API
# service's public URL (see Phase 8.5 setup notes for why this is
# needed on Render specifically).
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Must match the API's INGESTION_SECRET exactly, or every call fails
# with a 401 (or the API itself returns 500 if IT forgot to set one).
INGESTION_SECRET = os.environ.get("INGESTION_SECRET")

st.set_page_config(page_title="AI Commitment Intelligence", layout="wide")


# --- API calls -------------------------------------------------------------

def _headers() -> dict:
    headers = {}
    if INGESTION_SECRET:
        headers["X-Ingestion-Key"] = INGESTION_SECRET
    return headers


def call_process(text: str) -> dict:
    response = requests.post(
        f"{API_URL}/process",
        json={"text": text, "source": "dashboard"},
        headers=_headers(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def fetch_results() -> list:
    """Pulls the full shared results store from the API -- this is
    what makes Gmail-ingested commitments show up here too, not just
    ones pasted directly into this dashboard."""
    try:
        response = requests.get(
            f"{API_URL}/results", headers=_headers(), timeout=15
        )
        response.raise_for_status()
        return response.json().get("results", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Could not load results from the API: {e}")
        return []


def clear_results_remote() -> bool:
    try:
        response = requests.post(
            f"{API_URL}/results/clear", headers=_headers(), timeout=15
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"Could not clear results: {e}")
        return False


def check_health() -> dict | None:
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return None


# --- UI ---------------------------------------------------------------

st.title("📋 AI Commitment Intelligence")
st.caption(
    "Paste an email or thread below. The system extracts commitments, "
    "ranks them by urgency, and explains each ranking. If Gmail "
    "auto-ingestion (Phase 8.5) is running, those results appear here too."
)

health = check_health()
if health is None:
    st.error(
        f"⚠️ Cannot reach the API server at {API_URL}. "
        "Make sure it's running and API_URL is set correctly."
    )
elif not health.get("gemini_ready"):
    st.warning(
        "⚠️ API server is up, but Gemini isn't configured. "
        "Set GOOGLE_API_KEY on the API service and restart it."
    )
else:
    auth_note = " (ingestion key required)" if health.get("ingestion_key_configured") else ""
    st.success(
        f"✅ API connected — {health.get('sender_table_size', 0)} senders loaded.{auth_note}"
    )

st.divider()

col_input, col_actions = st.columns([3, 1])

with col_input:
    email_text = st.text_area(
        "Paste email or thread text",
        height=200,
        placeholder="Hi Priya, I'll send you the revised contract by Friday afternoon. "
                    "Also, can you review the attached budget by end of day tomorrow?",
    )

    uploaded_file = st.file_uploader(
        "...or upload a .txt / .eml file instead", type=["txt", "eml"]
    )
    if uploaded_file is not None:
        email_text = uploaded_file.read().decode("utf-8", errors="replace")
        st.text_area("File contents (loaded)", value=email_text, height=150, disabled=True)

with col_actions:
    st.write("")
    st.write("")
    process_clicked = st.button("🔍 Process", type="primary", use_container_width=True)
    clear_clicked = st.button("🗑️ Clear results", use_container_width=True)

if clear_clicked:
    if clear_results_remote():
        st.success("Results store cleared.")

if process_clicked:
    if not email_text or not email_text.strip():
        st.warning("Please paste some text or upload a file first.")
    elif health is None:
        st.error("Cannot process: API server is not reachable.")
    else:
        with st.spinner("Extracting and ranking commitments..."):
            try:
                result = call_process(email_text)
                new_items = result.get("ranked_commitments", [])
                if new_items:
                    st.success(f"Found {len(new_items)} commitment(s).")
                else:
                    st.info("No commitments found in this text.")
            except requests.exceptions.HTTPError as e:
                st.error(f"API returned an error: {e.response.status_code} — {e.response.text}")
            except requests.exceptions.RequestException as e:
                st.error(f"Could not reach the API: {e}")

st.divider()

st.subheader("Ranked Commitments")

hide_low_confidence = st.checkbox("Hide low-confidence items", value=True)

col_refresh, _ = st.columns([1, 4])
with col_refresh:
    if st.button("🔄 Refresh"):
        st.rerun()

store = fetch_results()
if hide_low_confidence:
    store = [item for item in store if item.get("confidence") != "low"]

if not store:
    st.info(
        "No commitments processed yet. Paste an email above and click "
        "Process, or wait for Gmail ingestion to find one."
    )
else:
    df = pd.DataFrame(store)

    display_cols = [
        "urgency_score", "commitment_text", "direction", "deadline_type",
        "deadline_text", "confidence", "sender", "recipient", "_source",
        "explanation",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display = df[display_cols].sort_values("urgency_score", ascending=False)

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "urgency_score": st.column_config.NumberColumn("Urgency", format="%.1f"),
            "commitment_text": st.column_config.TextColumn("Commitment", width="large"),
            "explanation": st.column_config.TextColumn("Why", width="large"),
            "_source": st.column_config.TextColumn("Source"),
        },
    )

    st.caption(f"{len(df_display)} commitment(s) total in the shared results store.")
