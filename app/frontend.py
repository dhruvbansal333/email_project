"""
Phase 7, Step 7.3 — Streamlit demo dashboard.
(Updated: Phase 8.5 — sends X-Ingestion-Key header on /process calls,
matching the shared-secret check added to app/main.py. main.py now
ALWAYS requires this key -- if INGESTION_SECRET isn't set as an
environment variable in this container, the API will return a 500
error on every /process call rather than silently allowing requests
through. Set INGESTION_SECRET in both the API's environment and here
before running.)

A paste/upload UI that calls the /process endpoint (built in Step 7.1)
and displays ranked, explained commitments in a table.

Run (with the FastAPI server already running in a separate terminal):
    pip install streamlit requests pandas
    streamlit run app/frontend.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

API_URL = "http://localhost:8000"
STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "results_store.json"

# Phase 8.5 addition: same secret as configured on the API side and in
# the Apps Script. Sent as a header on every /process call. If unset,
# no header is sent -- matches main.py's "skip check if unset" behavior.
INGESTION_SECRET = os.environ.get("INGESTION_SECRET")

st.set_page_config(page_title="AI Commitment Intelligence", layout="wide")


# --- Shared results store -----------------------------------------------

def load_store() -> list:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_store(items: list) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(items, indent=2))


def append_to_store(new_items: list, source_label: str) -> None:
    store = load_store()
    timestamp = datetime.now().isoformat(timespec="seconds")
    for item in new_items:
        item["_source"] = source_label
        item["_processed_at"] = timestamp
    store.extend(new_items)
    save_store(store)


# --- API call -------------------------------------------------------------

def _headers() -> dict:
    if INGESTION_SECRET:
        return {"X-Ingestion-Key": INGESTION_SECRET}
    return {}


def call_process(text: str) -> dict:
    response = requests.post(
        f"{API_URL}/process",
        json={"text": text},
        headers=_headers(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


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
    "ranks them by urgency, and explains each ranking."
)

health = check_health()
if health is None:
    st.error(
        "⚠️ Cannot reach the API server. Make sure it's running:\n\n"
        "`uvicorn app.main:app --reload --port 8000`"
    )
elif not health.get("gemini_ready"):
    st.warning(
        "⚠️ API server is up, but Gemini isn't configured. "
        "Set GOOGLE_API_KEY and restart the server."
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
    save_store([])
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
                    append_to_store(new_items, source_label="paste/upload")
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

store = load_store()
if hide_low_confidence:
    store = [item for item in store if item.get("confidence") != "low"]

if not store:
    st.info("No commitments processed yet. Paste an email above and click Process.")
else:
    df = pd.DataFrame(store)

    display_cols = [
        "urgency_score", "commitment_text", "direction", "deadline_type",
        "deadline_text", "confidence", "sender", "recipient", "explanation",
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
        },
    )

    st.caption(f"{len(df_display)} commitment(s) total in the results store.")
