"""
SQLite: метаданные + зашифрованные байты (BLOB).
Один файл БД на диске — удобно для облачного volume (/data).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DATA = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FLOWPHOTO_DATA_DIR", str(_DEFAULT_DATA)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "flowphoto.db"

DEFAULT_RETENTION_SECONDS = 30 * 24 * 3600  # 30 дней
MIN_RETENTION_SECONDS = 3600  # 1 час
MAX_RETENTION_SECONDS = 365 * 24 * 3600  # 1 год

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    short_id            TEXT PRIMARY KEY,
    original_name       TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    encrypted_data      BLOB NOT NULL,
    size_bytes          INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    retention_seconds   INTEGER NOT NULL DEFAULT 2592000,
    last_accessed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_photos_created ON photos(created_at);
CREATE INDEX IF NOT EXISTS idx_photos_last_access ON photos(last_accessed_at);
"""


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).astimezone(timezone.utc).isoformat()


def clamp_retention(seconds: int) -> int:
    return max(MIN_RETENTION_SECONDS, min(MAX_RETENTION_SECONDS, int(seconds)))


def init_db() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos'"
        ).fetchone()
        if rows:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if "encrypted_data" not in cols:
                conn.execute("DROP TABLE photos")
            else:
                if "retention_seconds" not in cols:
                    conn.execute(
                        f"ALTER TABLE photos ADD COLUMN retention_seconds INTEGER NOT NULL DEFAULT {DEFAULT_RETENTION_SECONDS}"
                    )
                if "last_accessed_at" not in cols:
                    conn.execute("ALTER TABLE photos ADD COLUMN last_accessed_at TEXT")
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _activity_at(photo: dict[str, Any]) -> datetime:
    ref = photo.get("last_accessed_at") or photo["created_at"]
    return _parse_iso(ref)


def is_photo_expired(photo: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or _utc_now()
    activity = _activity_at(photo)
    retention = photo.get("retention_seconds") or DEFAULT_RETENTION_SECONDS
    return (now - activity).total_seconds() > retention


def compute_expires_at(photo: dict[str, Any]) -> str:
    activity = _activity_at(photo)
    retention = photo.get("retention_seconds") or DEFAULT_RETENTION_SECONDS
    return _utc_iso(activity + timedelta(seconds=retention))


def photo_expiry_meta(photo: dict[str, Any]) -> dict[str, Any]:
    return {
        "retention_seconds": photo.get("retention_seconds") or DEFAULT_RETENTION_SECONDS,
        "last_accessed_at": photo.get("last_accessed_at"),
        "expires_at": compute_expires_at(photo),
        "expired": is_photo_expired(photo),
    }


def delete_photo(short_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM photos WHERE short_id = ?", (short_id,))
        conn.commit()
        return cur.rowcount > 0


def touch_photo_access(short_id: str) -> None:
    now = _utc_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE photos SET last_accessed_at = ? WHERE short_id = ?",
            (now, short_id),
        )
        conn.commit()


def cleanup_expired_photos() -> int:
    now = _utc_now()
    deleted = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT short_id, created_at, last_accessed_at, retention_seconds
            FROM photos
            """
        ).fetchall()
        for row in rows:
            photo = dict(row)
            if is_photo_expired(photo, now):
                conn.execute("DELETE FROM photos WHERE short_id = ?", (photo["short_id"],))
                deleted += 1
        conn.commit()
    return deleted


def insert_photo(
    short_id: str,
    original_name: str,
    mime_type: str,
    encrypted_data: bytes,
    size_bytes: int,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
) -> dict[str, Any]:
    created_at = _utc_iso()
    retention_seconds = clamp_retention(retention_seconds)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO photos (
                short_id, original_name, mime_type, encrypted_data, size_bytes,
                created_at, retention_seconds, last_accessed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                short_id,
                original_name,
                mime_type,
                encrypted_data,
                size_bytes,
                created_at,
                retention_seconds,
            ),
        )
        conn.commit()
    photo = {
        "short_id": short_id,
        "original_name": original_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_at": created_at,
        "retention_seconds": retention_seconds,
        "last_accessed_at": None,
    }
    return {**photo, **photo_expiry_meta(photo)}


def get_photo(short_id: str, *, touch_access: bool = False) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT short_id, original_name, mime_type, size_bytes, created_at,
                   retention_seconds, last_accessed_at
            FROM photos WHERE short_id = ?
            """,
            (short_id,),
        ).fetchone()
    if row is None:
        return None
    photo = dict(row)
    if is_photo_expired(photo):
        delete_photo(short_id)
        return None
    if touch_access:
        touch_photo_access(short_id)
        photo["last_accessed_at"] = _utc_iso()
    return {**photo, **photo_expiry_meta(photo)}


def get_encrypted_blob(short_id: str, *, touch_access: bool = True) -> bytes | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT encrypted_data, created_at, last_accessed_at, retention_seconds
            FROM photos WHERE short_id = ?
            """,
            (short_id,),
        ).fetchone()
    if row is None:
        return None
    photo = {
        "created_at": row["created_at"],
        "last_accessed_at": row["last_accessed_at"],
        "retention_seconds": row["retention_seconds"],
    }
    if is_photo_expired(photo):
        delete_photo(short_id)
        return None
    if touch_access:
        touch_photo_access(short_id)
    return row["encrypted_data"]