"""
SQLite: только метаданные. Зашифрованные байты — в uploads/.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "flowphoto.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    short_id      TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_created ON photos(created_at);
"""


def init_db() -> None:
    with get_connection() as conn:
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
    file_path: str,
    size_bytes: int,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO photos (short_id, original_name, mime_type, file_path, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (short_id, original_name, mime_type, file_path, size_bytes, created_at),
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
            "SELECT short_id, original_name, mime_type, file_path, size_bytes, created_at FROM photos WHERE short_id = ?",
            (short_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)