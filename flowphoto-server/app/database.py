"""
SQLite: метаданные + зашифрованные байты (BLOB).
Один файл БД на диске — удобно для облачного volume (/data).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DATA = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FLOWPHOTO_DATA_DIR", str(_DEFAULT_DATA)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "flowphoto.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    short_id        TEXT PRIMARY KEY,
    original_name   TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    encrypted_data  BLOB NOT NULL,
    size_bytes      INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_created ON photos(created_at);
"""


def init_db() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos'"
        ).fetchone()
        if rows:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if "encrypted_data" not in cols:
                conn.execute("DROP TABLE photos")
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


def insert_photo(
    short_id: str,
    original_name: str,
    mime_type: str,
    encrypted_data: bytes,
    size_bytes: int,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO photos (short_id, original_name, mime_type, encrypted_data, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (short_id, original_name, mime_type, encrypted_data, size_bytes, created_at),
        )
        conn.commit()
    return {
        "short_id": short_id,
        "original_name": original_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }


def get_photo(short_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT short_id, original_name, mime_type, size_bytes, created_at
            FROM photos WHERE short_id = ?
            """,
            (short_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_encrypted_blob(short_id: str) -> bytes | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT encrypted_data FROM photos WHERE short_id = ?",
            (short_id,),
        ).fetchone()
    if row is None:
        return None
    return row["encrypted_data"]