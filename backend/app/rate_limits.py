import hashlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)
RATE_LIMIT_MIGRATION_FILE = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20261111_01_create_api_rate_limit_windows.sql"
)
MAX_WINDOW_SECONDS = 3600
CLEANUP_INTERVAL_SECONDS = 60
_cleanup_lock = Lock()
_last_cleanup_at = 0.0

_UPSERT_WINDOW = text(
    """
    INSERT INTO api_rate_limit_windows (bucket_key, window_start, hit_count)
    VALUES (:bucket_key, :window_start, 1)
    ON CONFLICT (bucket_key) DO UPDATE SET
        hit_count = CASE
            WHEN api_rate_limit_windows.window_start = excluded.window_start
            THEN api_rate_limit_windows.hit_count + 1
            ELSE 1
        END,
        window_start = excluded.window_start
    RETURNING hit_count
    """
)


def ensure_rate_limit_storage(connection: Connection) -> None:
    migration_sql = RATE_LIMIT_MIGRATION_FILE.read_text(encoding="utf-8")
    for statement in migration_sql.split(";"):
        if statement.strip():
            connection.exec_driver_sql(statement)


def _client_bucket(request: Request, name: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    client_hash = hashlib.sha256(client_host.encode("utf-8")).hexdigest()
    return f"client:{name}:{client_hash}"


def _consume_window(
    db: Session,
    bucket_key: str,
    limit: int,
    window_seconds: int,
) -> int:
    now = int(time.time())
    window_start = now - now % window_seconds
    global _last_cleanup_at
    with _cleanup_lock:
        monotonic_now = time.monotonic()
        if monotonic_now - _last_cleanup_at >= CLEANUP_INTERVAL_SECONDS:
            db.execute(
                text("DELETE FROM api_rate_limit_windows WHERE window_start < :cutoff"),
                {"cutoff": now - MAX_WINDOW_SECONDS},
            )
            _last_cleanup_at = monotonic_now
    count = db.execute(
        _UPSERT_WINDOW,
        {"bucket_key": bucket_key, "window_start": window_start},
    ).scalar_one()
    db.commit()
    if count > limit:
        return window_start + window_seconds - now
    return 0


def rate_limit(
    name: str,
    limit: int,
    window_seconds: int,
    *,
    scope: str = "client",
) -> Callable[..., None]:
    if scope not in {"client", "global"}:
        raise ValueError("Rate-limit scope must be 'client' or 'global'.")
    if limit < 1 or not 1 <= window_seconds <= MAX_WINDOW_SECONDS:
        raise ValueError("Rate-limit values are outside supported bounds.")

    def enforce(request: Request, db: Session = Depends(get_db)) -> None:
        bucket_key = (
            _client_bucket(request, name)
            if scope == "client"
            else f"global:{name}"
        )
        try:
            retry_after = _consume_window(db, bucket_key, limit, window_seconds)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.error(
                "Rate-limit storage failed exception_class=%s scope=%s",
                type(exc).__name__,
                scope,
            )
            raise HTTPException(
                status_code=503,
                detail="Request protection is temporarily unavailable.",
            ) from exc
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    enforce.__name__ = f"rate_limit_{scope}_{name}"
    return enforce
