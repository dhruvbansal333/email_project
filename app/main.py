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

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

import psycopg2


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

# Multi-user extension (Task 3): database + authentication helpers
from db import get_conn
from auth import (
    validate_userid,
    validate_password,
    hash_password,
    verify_password,
    burn_dummy_check,
    create_session_token,
    decode_session_token,
    session_secret_configured,
    SESSION_TTL_SECONDS,
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

    if not os.environ.get("DATABASE_URL"):
        print("WARNING: DATABASE_URL is not set. /signup and /login will return 503.")
    if not session_secret_configured():
        print("WARNING: SESSION_SECRET missing or shorter than 32 chars. /signup and /login will return 503.")


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
        "auth_ready": bool(os.environ.get("DATABASE_URL")) and session_secret_configured(),
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


# =========================================================
# Multi-user extension, Task 3: signup / login / session tokens
#
# Existing endpoints above are deliberately UNCHANGED in this task.
# Task 4 will switch /process, /results, /results/clear over to
# per-user authentication (session token OR personal API key).
# =========================================================

MAX_USER_ACCOUNTS = 15  # total accounts allowed, per the roadmap's limits

# ---------------------------------------------------------
# Simple failed-login throttle (in-memory, per userid).
#
# Purpose: stop someone guessing passwords at speed. After
# LOGIN_MAX_FAILURES wrong attempts within LOGIN_WINDOW_SECONDS,
# further attempts for that userid get 429 until the window passes.
# Known trade-offs (fine at this scale, worth stating in the report):
#   - resets if the service restarts
#   - someone could deliberately lock out another person's userid
#     for a few minutes (it does not reveal or expose any data)
# ---------------------------------------------------------

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 10 * 60
_THROTTLE_MAX_KEYS = 5000   # bounds memory if someone sprays random userids

_failed_logins: dict = {}


def _prune_failures(key: str) -> list:
    cutoff = time.time() - LOGIN_WINDOW_SECONDS
    recent = [t for t in _failed_logins.get(key, []) if t > cutoff]
    if recent:
        _failed_logins[key] = recent
    else:
        _failed_logins.pop(key, None)
    return recent


def _check_login_throttle(key: str) -> None:
    if len(_prune_failures(key)) >= LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please wait a few minutes and try again.",
        )


def _record_login_failure(key: str) -> None:
    if len(_failed_logins) >= _THROTTLE_MAX_KEYS:
        _failed_logins.clear()
    _failed_logins.setdefault(key, []).append(time.time())


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------

class SignupRequest(BaseModel):
    userid: str
    password: str


class LoginRequest(BaseModel):
    userid: str
    password: str


class AuthResponse(BaseModel):
    token: str
    userid: str
    expires_in: int


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _require_auth_config() -> None:
    if not os.environ.get("DATABASE_URL") or not session_secret_configured():
        raise HTTPException(
            status_code=503,
            detail="Account system is not configured on the server.",
        )


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Reads 'Authorization: Bearer <token>' and returns
    {'id': <db user id>, 'userid': <name>}. Raises 401 otherwise."""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")

    claims = decode_session_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")

    try:
        return {"id": int(claims["sub"]), "userid": claims["uid"]}
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")


# ---------------------------------------------------------
# POST /signup  -- create an account and log in immediately
# ---------------------------------------------------------

@app.post("/signup", response_model=AuthResponse)
def signup(payload: SignupRequest):

    _require_auth_config()

    # Userids are case-insensitive: "Dhruv" and "dhruv" are the same account.
    userid = payload.userid.strip().lower()

    error = validate_userid(userid) or validate_password(payload.password)
    if error:
        raise HTTPException(status_code=422, detail=error)

    password_hash = hash_password(payload.password)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Serialize signups so two people can't both slip past
                # the account cap at the same moment.
                cur.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")

                cur.execute("SELECT COUNT(*) FROM users")
                (count,) = cur.fetchone()
                if count >= MAX_USER_ACCOUNTS:
                    raise HTTPException(
                        status_code=403,
                        detail="Signups are closed: this demo has reached its account limit.",
                    )

                cur.execute(
                    "INSERT INTO users (userid, password_hash) VALUES (%s, %s) RETURNING id",
                    (userid, password_hash),
                )
                (user_db_id,) = cur.fetchone()

    except psycopg2.errors.UniqueViolation:
        # Unavoidable on signup: the person must be told the name is taken.
        raise HTTPException(status_code=409, detail="That userid is already taken.")
    except psycopg2.OperationalError:
        raise HTTPException(
            status_code=503,
            detail="Database is temporarily unavailable. Please try again in a moment.",
        )

    return {
        "token": create_session_token(user_db_id, userid),
        "userid": userid,
        "expires_in": SESSION_TTL_SECONDS,
    }


# ---------------------------------------------------------
# POST /login
#
# Every failure returns the SAME generic 401, whether the userid
# doesn't exist or the password is wrong -- so the endpoint never
# reveals which userids are registered.
# ---------------------------------------------------------

@app.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):

    _require_auth_config()

    userid = payload.userid.strip().lower()
    _check_login_throttle(userid)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, password_hash FROM users WHERE userid = %s",
                    (userid,),
                )
                row = cur.fetchone()
    except psycopg2.OperationalError:
        raise HTTPException(
            status_code=503,
            detail="Database is temporarily unavailable. Please try again in a moment.",
        )

    generic_failure = HTTPException(status_code=401, detail="Invalid userid or password.")

    if row is None:
        burn_dummy_check(payload.password)   # equalize response time
        _record_login_failure(userid)
        raise generic_failure

    user_db_id, password_hash = row

    if not verify_password(payload.password, password_hash):
        _record_login_failure(userid)
        raise generic_failure

    _failed_logins.pop(userid, None)

    return {
        "token": create_session_token(user_db_id, userid),
        "userid": userid,
        "expires_in": SESSION_TTL_SECONDS,
    }


# ---------------------------------------------------------
# GET /me  -- "who am I?" Confirms a session token is valid and
# that the account still exists. The dashboard will use this to
# decide whether to show the login screen.
# ---------------------------------------------------------

@app.get("/me")
def me(user: dict = Depends(get_current_user)):

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT userid, created_at FROM users WHERE id = %s",
                    (user["id"],),
                )
                row = cur.fetchone()
    except psycopg2.OperationalError:
        raise HTTPException(
            status_code=503,
            detail="Database is temporarily unavailable. Please try again in a moment.",
        )

    if row is None:
        # Valid token but the account was deleted.
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")

    return {"userid": row[0], "created_at": row[1].isoformat()}
