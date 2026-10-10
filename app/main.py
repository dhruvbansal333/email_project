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

import hmac
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
    generate_api_key,
    hash_api_key,
    API_KEY_PREFIX,
    API_KEY_MAX_LENGTH,
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


def _db_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Database is temporarily unavailable. Please try again in a moment.",
    )


_UNAUTHORIZED = "Missing or invalid credentials."


def _principal_from_session(authorization: str) -> dict:
    """'Authorization: Bearer <session token>' -> a logged-in user."""

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    _require_auth_config()

    claims = decode_session_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    try:
        user_db_id = int(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    # A token can outlive its account (tokens last 12h). Confirm the
    # account still exists so a deleted user is locked out immediately.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, userid FROM users WHERE id = %s", (user_db_id,))
                row = cur.fetchone()
    except psycopg2.OperationalError:
        raise _db_unavailable()

    if row is None:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    return {"kind": "user", "via": "session", "id": row[0], "userid": row[1]}


def _principal_from_api_key(raw_key: str) -> dict:
    """'X-API-Key: cai_...' -> the user who owns that key."""

    key = raw_key.strip()
    if not key.startswith(API_KEY_PREFIX) or len(key) > API_KEY_MAX_LENGTH:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Account system is not configured on the server.")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT u.id, u.userid FROM api_keys k "
                    "JOIN users u ON u.id = k.user_id WHERE k.key_hash = %s",
                    (hash_api_key(key),),
                )
                row = cur.fetchone()
    except psycopg2.OperationalError:
        raise _db_unavailable()

    if row is None:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)

    return {"kind": "user", "via": "apikey", "id": row[0], "userid": row[1]}


def resolve_principal(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    x_ingestion_key: Optional[str] = Header(None),
) -> dict:
    """
    Works out WHO is calling. Used by every protected endpoint.

    Accepts, in this order (only the first one present is considered; if
    it is invalid the request is rejected, never "tried" against the next):
      1. Authorization: Bearer <session token>   -> dashboard login
      2. X-API-Key: cai_...                        -> a user's Gmail script
      3. X-Ingestion-Key: <global secret>          -> LEGACY (transition only)

    The legacy path is the original single-user design, kept so the live
    dashboard and Gmail script keep working until they're moved to per-user
    credentials. It uses its own separate in-memory store and can never see
    or touch a user's data. It switches itself off when INGESTION_SECRET is
    removed from the server's environment -- no code change needed.
    """

    if authorization is not None:
        return _principal_from_session(authorization)

    if x_api_key is not None:
        return _principal_from_api_key(x_api_key)

    if x_ingestion_key and INGESTION_SECRET and hmac.compare_digest(
        x_ingestion_key.encode("utf-8"), INGESTION_SECRET.encode("utf-8")
    ):
        return {"kind": "legacy", "via": "ingestion_key"}

    raise HTTPException(status_code=401, detail=_UNAUTHORIZED)


# ---------------------------------------------------------
# Per-user result storage (Neon Postgres)
# ---------------------------------------------------------

_ALLOWED_SOURCES = {"dashboard", "gmail"}


def _normalize_source(source: Optional[str]) -> str:
    """'source' is caller-supplied free text; only store known values."""
    return source if source in _ALLOWED_SOURCES else "other"


def _save_user_results(user_id: int, ranked: list, source: str) -> None:
    if not ranked:
        return

    rows = [
        (
            user_id,
            r.get("commitment_text"),
            r.get("direction"),
            r.get("deadline_type"),
            r.get("deadline_text"),
            r.get("confidence"),
            r.get("sender"),
            r.get("recipient"),
            r.get("urgency_score"),
            r.get("explanation"),
            source,
        )
        for r in ranked
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO results (user_id, commitment_text, direction, "
                "deadline_type, deadline_text, confidence, sender, recipient, "
                "urgency_score, explanation, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
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

    if INGESTION_SECRET:
        print("Legacy ingestion key ENABLED (transition mode). Remove INGESTION_SECRET to disable it.")
    else:
        print("Legacy ingestion key disabled. Only user sessions and personal API keys are accepted.")

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
    principal: dict = Depends(resolve_principal)
):

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
def process(
    payload: EmailInput,
    principal: dict = Depends(resolve_principal)
):

    """
    Full pipeline:

    1. Extract commitments using Gemini.
    2. Compute ranking features.
    3. Calculate urgency score.
    4. Generate ranking explanation.
    5. Sort commitments by urgency score.

    Requires credentials (see resolve_principal): a login session token,
    a personal API key, or -- during the transition -- the legacy ingestion
    key. Results are saved under the caller's own account.
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
    # Step 3.5: Save into the shared results store (Phase 8.5)
    # so both the dashboard and Gmail ingestion see the same data,
    # regardless of which one triggered this processing run.
    # -----------------------------------------------------

    if principal["kind"] == "legacy":

        # Original single-user path: separate in-memory store, unchanged.
        processed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        for item in ranked:
            _results_store.append({
                **item,
                "_source": payload.source,
                "_processed_at": processed_at,
            })

    else:

        # Per-user path: saved to Neon under this user's id only.
        # If saving fails we return an error rather than "succeed" with the
        # data lost: the Gmail script then leaves the email unlabeled and
        # retries it on the next poll.
        try:
            _save_user_results(
                principal["id"], ranked, _normalize_source(payload.source)
            )
        except psycopg2.errors.ForeignKeyViolation:
            # Account was deleted between authentication and saving.
            raise HTTPException(status_code=401, detail=_UNAUTHORIZED)
        except psycopg2.OperationalError:
            raise _db_unavailable()

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
def get_results(principal: dict = Depends(resolve_principal)):
    """Everything THIS caller has processed, highest urgency first.
    A user sees only their own rows -- whether they authenticate with a
    login session or with their API key, it resolves to the same account."""

    if principal["kind"] == "legacy":
        sorted_results = sorted(
            _results_store,
            key=lambda x: x.get("urgency_score", 0),
            reverse=True
        )
        return {"results": sorted_results}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT commitment_text, direction, deadline_type, deadline_text, "
                    "confidence, sender, recipient, urgency_score, explanation, "
                    "source, processed_at FROM results WHERE user_id = %s "
                    "ORDER BY urgency_score DESC, id DESC",
                    (principal["id"],),
                )
                rows = cur.fetchall()
    except psycopg2.OperationalError:
        raise _db_unavailable()

    return {
        "results": [
            {
                "commitment_text": r[0],
                "direction": r[1],
                "deadline_type": r[2],
                "deadline_text": r[3],
                "confidence": r[4],
                "sender": r[5],
                "recipient": r[6],
                "urgency_score": r[7],
                "explanation": r[8],
                "_source": r[9],
                "_processed_at": r[10].isoformat(),
            }
            for r in rows
        ]
    }


@app.post("/results/clear")
def clear_results(principal: dict = Depends(resolve_principal)):
    """'Delete my data': removes every stored result belonging to the
    caller. Other users' results are never touched."""

    if principal["kind"] == "legacy":
        _results_store.clear()
        return {"status": "cleared"}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM results WHERE user_id = %s", (principal["id"],))
                deleted = cur.rowcount
    except psycopg2.OperationalError:
        raise _db_unavailable()

    return {"status": "cleared", "deleted": deleted}


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


# =========================================================
# Multi-user extension, Task 4: API keys + account deletion
# =========================================================

def _require_session_user(principal: dict) -> None:
    """Key management and account deletion need a real login session.
    A personal API key (which lives inside a script file and could leak)
    must never be able to mint new keys or delete the account."""

    if principal["kind"] != "user" or principal["via"] != "session":
        raise HTTPException(
            status_code=403,
            detail="This action requires you to be logged in (a login session, not an API key).",
        )


# ---------------------------------------------------------
# POST /apikey -- create (or replace) the caller's Gmail-script key.
# The plaintext key is returned ONCE, here, and never stored: only its
# hash is kept, so it can't be shown again. Creating a new key
# immediately invalidates the previous one.
# ---------------------------------------------------------

@app.post("/apikey")
def create_api_key(principal: dict = Depends(resolve_principal)):

    _require_session_user(principal)

    key = generate_api_key()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO api_keys (user_id, key_hash) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE "
                    "SET key_hash = EXCLUDED.key_hash, created_at = now() "
                    "RETURNING created_at",
                    (principal["id"], hash_api_key(key)),
                )
                (created_at,) = cur.fetchone()
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED)
    except psycopg2.OperationalError:
        raise _db_unavailable()

    return {
        "api_key": key,
        "created_at": created_at.isoformat(),
        "note": "Save this key now. It is shown only once and cannot be recovered.",
    }


# ---------------------------------------------------------
# GET /apikey -- does the caller have a key? (never reveals the key)
# ---------------------------------------------------------

@app.get("/apikey")
def api_key_status(principal: dict = Depends(resolve_principal)):

    _require_session_user(principal)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT created_at FROM api_keys WHERE user_id = %s",
                    (principal["id"],),
                )
                row = cur.fetchone()
    except psycopg2.OperationalError:
        raise _db_unavailable()

    if row is None:
        return {"has_key": False, "created_at": None}
    return {"has_key": True, "created_at": row[0].isoformat()}


# ---------------------------------------------------------
# POST /account/delete -- permanently delete the account.
# Requires the current password as a second confirmation, so a stolen
# session token alone can't wipe an account. The database cascade then
# removes the user's results, API key and usage counters with it, so
# nothing is left behind. Wrong passwords count toward the same lockout
# as /login, so this can't be used to guess passwords either.
# ---------------------------------------------------------

class DeleteAccountRequest(BaseModel):
    password: str


@app.post("/account/delete")
def delete_account(
    payload: DeleteAccountRequest,
    principal: dict = Depends(resolve_principal),
):

    _require_session_user(principal)

    throttle_key = principal["userid"]
    _check_login_throttle(throttle_key)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE id = %s",
                    (principal["id"],),
                )
                row = cur.fetchone()

                if row is None or not verify_password(payload.password, row[0]):
                    _record_login_failure(throttle_key)
                    raise HTTPException(status_code=401, detail="Incorrect password.")

                cur.execute("DELETE FROM users WHERE id = %s", (principal["id"],))
    except psycopg2.OperationalError:
        raise _db_unavailable()

    _failed_logins.pop(throttle_key, None)
    return {"status": "deleted"}
