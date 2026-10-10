"""
Multi-user extension, Task 3 -- authentication helpers.

- Passwords are hashed with bcrypt. The plaintext is never stored or logged.
- Session tokens are signed JWTs (HS256) that expire after SESSION_TTL_SECONDS.
  They are stateless: nothing is stored server-side, so no extra database
  table is needed. The trade-off is that a token cannot be revoked before it
  expires (acceptable here; the lifetime is short).
- Requires the SESSION_SECRET environment variable (32+ characters).
"""

import hashlib
import os
import re
import secrets
import time
from typing import Optional

import bcrypt
import jwt

SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours

USERID_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")

MIN_PASSWORD_LENGTH = 8
# bcrypt only uses the first 72 BYTES of a password. Rather than silently
# truncating, we reject anything longer so users aren't misled.
MAX_PASSWORD_BYTES = 72


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_userid(userid: str) -> Optional[str]:
    """Returns an error message, or None if the userid is acceptable."""
    if not USERID_PATTERN.match(userid or ""):
        return "Userid must be 3-32 characters: letters, numbers, underscore only."
    return None


def validate_password(password: str) -> Optional[str]:
    """Returns an error message, or None if the password is acceptable."""
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password is too long (max {MAX_PASSWORD_BYTES} bytes)."
    return None


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# A real bcrypt hash of a throwaway string. When a login names a userid that
# does not exist, we still run one bcrypt comparison against this, so the
# response takes about as long as a real wrong-password attempt. Without it,
# response time would reveal which userids exist.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode("utf-8")


def burn_dummy_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

def _session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET is not set (or shorter than 32 characters). "
            "Add a long random value as an environment variable on the API service."
        )
    return secret


def session_secret_configured() -> bool:
    secret = os.environ.get("SESSION_SECRET")
    return bool(secret and len(secret) >= 32)


def create_session_token(user_id: int, userid: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),   # JWT spec: subject must be a string
        "uid": userid,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def decode_session_token(token: str) -> Optional[dict]:
    """Returns the token's payload if valid and unexpired, else None."""
    try:
        return jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Personal API keys (used by the Gmail Apps Script)
#
# A key is 256 bits of randomness, so a plain SHA-256 hash is appropriate
# (bcrypt's slowness exists to protect low-entropy human passwords; it would
# only add cost here). Only the hash is stored. The plaintext key is shown to
# the user exactly once, at creation.
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "cai_"
API_KEY_MAX_LENGTH = 200   # reject absurd inputs before hashing


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
