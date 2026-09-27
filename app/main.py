"""
Phase 7, Step 7.1 — API layer.
Phase 8.5 — Security update: shared-secret authentication added.

Wraps the full pipeline (extraction -> ranking -> explanation)
in a FastAPI service.

Uses the free Gemini API for extraction.
Ranking reuses the rule-based scorer and feature engineering
built in Phase 5.

SECURITY (Phase 8.5): /process and /extract now require a matching
X-Ingestion-Key header. This stops arbitrary internet traffic from
hitting the API and burning Gemini quota. Both the Streamlit dashboard
and the Google Apps Script must send this header.

Run:
    uvicorn app.main:app --reload --port 8000

Test:
    Open http://localhost:8000/docs
"""

import os
import time
import json
import sys

from collections import Counter
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel


# ---------------------------------------------------------
# Import project modules
# ---------------------------------------------------------

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from gemini_extractor import extract_commitments, get_client
from rank_features import (
    compute_features,
    build_sender_frequency_table
)
from rank_score import (
    score_commitment,
    generate_explanation
)


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="AI Commitment Intelligence API",
    description="Extracts, ranks, and explains commitments from email text.",
    version="0.1.0",
)


# ---------------------------------------------------------
# Paths and global resources
# ---------------------------------------------------------

DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "gold_set"
    / "v1"
)


_sender_freq_table = Counter()
_max_sender_freq = 1
_gemini_client = None

# ---------------------------------------------------------
# Phase 8.5 (continued): shared results store.
#
# Why this lives here, not in the dashboard: the dashboard and the
# Gmail Apps Script are now two independent callers of this same API,
# potentially running as two separate Render services with separate
# filesystems. If each kept its own local copy of "everything
# processed so far," the dashboard would never see what Gmail
# ingestion found. Keeping the store here, server-side, means both
# callers see the exact same data.
#
# Known limitation (same category as your other free-tier trade-offs,
# already documented elsewhere in the project): this is in-memory,
# so it resets if the service restarts. Fine for a demo; would need a
# real database for production persistence.
# ---------------------------------------------------------

_results_store: List[dict] = []


# ---------------------------------------------------------
# Security (Phase 8.5): shared secret required on every call
# to /extract and /process. Set as an environment variable —
# never hardcoded, never committed to Git.
# ---------------------------------------------------------

INGESTION_SECRET = os.environ.get("INGESTION_SECRET")


def verify_ingestion_key(x_ingestion_key: Optional[str]) -> None:
    """Raises 401 if the key is missing/wrong. Raises 500 with a
    clear message if the server itself forgot to set the secret —
    fail loud, not silently open."""

    if not INGESTION_SECRET:
        raise HTTPException(
            status_code=500,
            detail=(
                "Server misconfigured: INGESTION_SECRET is not set. "
                "Refusing to run with no authentication rather than "
                "silently allowing all requests."
            ),
        )

    if x_ingestion_key != INGESTION_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Ingestion-Key header."
        )


# ---------------------------------------------------------
# Startup: Load resources
# ---------------------------------------------------------

@app.on_event("startup")
def load_resources():

    global _sender_freq_table
    global _max_sender_freq
    global _gemini_client

    all_commitments = []

    for split in ["gold_train.json", "gold_val.json"]:

        path = DATA_DIR / split

        if path.exists():

            with open(path, "r", encoding="utf-8") as file:
                all_commitments.extend(json.load(file))

    if all_commitments:

        _sender_freq_table = build_sender_frequency_table(
            all_commitments
        )

        _max_sender_freq = (
            max(_sender_freq_table.values())
            if _sender_freq_table
            else 1
        )

        print(
            f"Loaded sender frequency table: "
            f"{len(_sender_freq_table)} senders"
        )

    else:

        print(
            "WARNING: no gold-set files found — "
            "sender_importance will use defaults for everyone"
        )

    try:

        _gemini_client = get_client()

        print("Gemini client ready.")

    except RuntimeError as e:

        print(f"WARNING: {e}")

        print(
            "The /extract and /process endpoints "
            "will fail until GOOGLE_API_KEY is set."
        )

    if not INGESTION_SECRET:
        print(
            "WARNING: INGESTION_SECRET is not set. "
            "/extract and /process will return 500 until it is configured."
        )
    else:
        print("Ingestion key configured — /extract and /process require it.")


# ---------------------------------------------------------
# Pydantic request and response models
# ---------------------------------------------------------

class EmailInput(BaseModel):

    text: str

    # Phase 8.5: which caller sent this ("dashboard" or "gmail"), purely
    # for display in the results table. Optional so nothing breaks if a
    # caller doesn't send it.
    source: Optional[str] = "unspecified"


class ExtractResponse(BaseModel):

    commitments: list


class RankedCommitment(BaseModel):

    commitment_text: str

    direction: str

    deadline_type: str

    deadline_text: Optional[str] = None

    confidence: str

    sender: Optional[str] = None

    recipient: Optional[str] = None

    urgency_score: float

    explanation: str


class ProcessResponse(BaseModel):

    ranked_commitments: List[RankedCommitment]


# ---------------------------------------------------------
# Health endpoint — intentionally NOT secured, so you (and
# Render's own health checks) can always confirm the service
# is up without needing the secret.
# ---------------------------------------------------------

@app.get("/health")
def health():

    return {
        "status": "ok",
        "gemini_ready": _gemini_client is not None,
        "sender_table_size": len(_sender_freq_table),
        "ingestion_key_configured": INGESTION_SECRET is not None,
    }


# ---------------------------------------------------------
# Extraction endpoint
# ---------------------------------------------------------

@app.post("/extract", response_model=ExtractResponse)
def extract(
    payload: EmailInput,
    x_ingestion_key: Optional[str] = Header(None)
):

    """
    Extraction only — no ranking.

    Useful for debugging the LLM's raw output
    before it goes through scoring.
    """

    verify_ingestion_key(x_ingestion_key)

    if _gemini_client is None:

        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini client not configured. "
                "Set GOOGLE_API_KEY and restart."
            )
        )

    try:

        commitments = extract_commitments(
            payload.text,
            client=_gemini_client
        )

    except ValueError as e:

        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed: {e}"
        )

    return {
        "commitments": commitments
    }


# ---------------------------------------------------------
# Full processing endpoint
# ---------------------------------------------------------

@app.post("/process", response_model=ProcessResponse)
def process(
    payload: EmailInput,
    x_ingestion_key: Optional[str] = Header(None)
):

    """
    Full pipeline:

    1. Extract commitments using Gemini.
    2. Compute ranking features.
    3. Calculate urgency score.
    4. Generate ranking explanation.
    5. Sort commitments by urgency score.

    Requires a valid X-Ingestion-Key header (Phase 8.5 security update).
    Called by both the Streamlit dashboard and the Gmail Apps Script.
    """

    verify_ingestion_key(x_ingestion_key)

    if _gemini_client is None:

        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini client not configured. "
                "Set GOOGLE_API_KEY and restart."
            )
        )

    # -----------------------------------------------------
    # Start total processing timer
    # -----------------------------------------------------

    start_time = time.time()

    # -----------------------------------------------------
    # Step 1: Extract commitments
    # -----------------------------------------------------

    try:

        raw_commitments = extract_commitments(
            payload.text,
            client=_gemini_client
        )

        extraction_time = time.time() - start_time

        print(
            f"Gemini extraction time: "
            f"{extraction_time:.2f} seconds"
        )

        print(
            f"Commitments extracted: "
            f"{len(raw_commitments)}"
        )

    except ValueError as e:

        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed: {e}"
        )

    # -----------------------------------------------------
    # Step 2: Rank extracted commitments
    # -----------------------------------------------------

    ranked = []

    ranking_start_time = time.time()

    for c in raw_commitments:

        # Normalize field names between the extractor's
        # output schema and the ranking module's schema.

        normalized = {

            "commitment_text": c.get(
                "commitment_text"
            ),

            "direction": c.get(
                "direction"
            ),

            "deadline_type": c.get(
                "deadline_type",
                "none"
            ),

            "deadline_text": c.get(
                "deadline_text"
            ),

            "confidence": c.get(
                "confidence",
                "medium"
            ),

            "sender": c.get(
                "sender_text"
            ),

            "recipient": c.get(
                "recipient_text"
            ),
        }

        # Compute ranking features

        features = compute_features(
            normalized,
            _sender_freq_table,
            _max_sender_freq
        )

        # Calculate urgency score

        score = score_commitment(
            features
        )

        # Generate explanation

        explanation = generate_explanation(
            normalized,
            features,
            score
        )

        # Store ranked commitment

        ranked.append({

            **normalized,

            "urgency_score": score,

            "explanation": explanation,

        })

    ranking_time = time.time() - ranking_start_time

    print(
        f"Ranking time: "
        f"{ranking_time:.2f} seconds"
    )

    # -----------------------------------------------------
    # Step 3: Sort by urgency score
    # -----------------------------------------------------

    ranked.sort(
        key=lambda x: x["urgency_score"],
        reverse=True
    )

    # -----------------------------------------------------
    # Step 3.5: Save into the shared results store (Phase 8.5)
    # so both the dashboard and Gmail ingestion see the same data,
    # regardless of which one triggered this processing run.
    # -----------------------------------------------------

    processed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    for item in ranked:
        _results_store.append({
            **item,
            "_source": payload.source,
            "_processed_at": processed_at,
        })

    # -----------------------------------------------------
    # Step 4: Print total processing time
    # -----------------------------------------------------

    total_time = time.time() - start_time

    print(
        f"Total processing time: "
        f"{total_time:.2f} seconds"
    )

    # -----------------------------------------------------
    # Step 5: Return response
    # -----------------------------------------------------

    return {
        "ranked_commitments": ranked
    }


# ---------------------------------------------------------
# Phase 8.5: shared results store endpoints.
# Secured the same way as /process -- only callers with the correct
# key can read or clear results.
# ---------------------------------------------------------

@app.get("/results")
def get_results(x_ingestion_key: Optional[str] = Header(None)):
    """Returns everything processed so far, from either source
    (dashboard paste/upload or Gmail ingestion), newest-scored first."""

    verify_ingestion_key(x_ingestion_key)

    sorted_results = sorted(
        _results_store,
        key=lambda x: x.get("urgency_score", 0),
        reverse=True
    )
    return {"results": sorted_results}


@app.post("/results/clear")
def clear_results(x_ingestion_key: Optional[str] = Header(None)):
    """Empties the shared results store. Used by the dashboard's
    'Clear results' button."""

    verify_ingestion_key(x_ingestion_key)

    _results_store.clear()
    return {"status": "cleared"}
