"""Migrate and seed the database for a hosted deployment (Vercel), safely from many instances at once.

Runs on the first API request of each new serverless instance (AUTO_SETUP). Once the schema is at head
and the 5 demo people exist it only costs a couple of quick queries. It can also be run by hand:

    DATABASE_URL=... python -m app.deploy_setup
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import _normalize_db_url, get_settings

log = logging.getLogger("astitva.setup")
_LOCK_KEY = 0x41535449  # "ASTI"
_done = False
_mutex = threading.Lock()


def _direct_url() -> str:
    # Advisory locks need a real session, not PgBouncer's transaction pooling, so prefer the direct URL.
    env = os.environ
    url = next((env[k] for k in sorted(env) if k.endswith(("DATABASE_URL_UNPOOLED", "POSTGRES_URL_NON_POOLING")) and env[k]),
               None) or get_settings().database_url
    return _normalize_db_url(url)


def run() -> None:
    from alembic import command
    from alembic.config import Config

    from app import seed

    root = Path(__file__).resolve().parent.parent
    eng = create_engine(_direct_url(), poolclass=NullPool, connect_args={"prepare_threshold": None})
    with eng.connect() as conn:
        conn.execute(text("select pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            cfg = Config(str(root / "alembic.ini"))
            cfg.set_main_option("script_location", str(root / "alembic"))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
            mode = get_settings().seed_mode
            if mode in ("clean", "demo"):
                seed.run(clean=(mode == "clean"))
        finally:
            conn.execute(text("select pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            conn.commit()
    eng.dispose()


def ensure() -> None:
    """Once per process. A failure is logged and retried on the next request."""
    global _done
    if _done:
        return
    with _mutex:
        if _done:
            return
        run()
        _done = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
    print("Database is migrated and seeded.")
