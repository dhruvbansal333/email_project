"""
Multi-user extension, Task 3 -- database connection helper.

Opens a short-lived connection to Neon Postgres per request, commits on
success, rolls back on any error, and always closes. At this project's
scale (a handful of users) one-connection-per-request is simple and
perfectly adequate; a connection pool would be the next step for real
traffic.

Requires the DATABASE_URL environment variable (set on the API service
in Render -- never committed to Git).
"""

import os
from contextlib import contextmanager

import psycopg2


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add your Neon connection string "
            "as an environment variable on the API service."
        )
    return url


@contextmanager
def get_conn():
    """Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    Commits automatically if the block succeeds, rolls back if it raises.
    """
    # connect_timeout: Neon's free compute auto-suspends when idle, so the
    # first connection after a quiet period can take a moment to wake up.
    conn = psycopg2.connect(get_database_url(), connect_timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
