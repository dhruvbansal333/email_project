
"""
Phase 7, Step 7.1 — API layer.

Wraps the full pipeline (extraction -> ranking -> explanation)
in a FastAPI service.

Uses the free Gemini API for extraction.
Ranking reuses the rule-based scorer and feature engineering
built in Phase 5.

Run:
    uvicorn app.main:app --reload --port 8000

Test:
    Open http://localhost:8000/docs
"""

import time
import json
import sys

from collections import Counter
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException
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


# ---------------------------------------------------------
# Pydantic request and response models
# ---------------------------------------------------------

class EmailInput(BaseModel):

    text: str


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
# Health endpoint
# ---------------------------------------------------------

@app.get("/health")
def health():

    return {
        "status": "ok",
        "gemini_ready": _gemini_client is not None,
        "sender_table_size": len(_sender_freq_table),
    }


# ---------------------------------------------------------
# Extraction endpoint
# ---------------------------------------------------------

@app.post("/extract", response_model=ExtractResponse)
def extract(payload: EmailInput):

    """
    Extraction only — no ranking.

    Useful for debugging the LLM's raw output
    before it goes through scoring.
    """

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
def process(payload: EmailInput):

    """
    Full pipeline:

    1. Extract commitments using Gemini.
    2. Compute ranking features.
    3. Calculate urgency score.
    4. Generate ranking explanation.
    5. Sort commitments by urgency score.

    This endpoint is used by the Streamlit dashboard.
    """

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