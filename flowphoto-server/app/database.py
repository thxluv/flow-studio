"""
SQLite: метаданные + зашифрованные байты (BLOB).
Один файл БД на диске — удобно для облачного volume (/data).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DATA = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FLOWPHOTO_DATA_DIR", str(_DEFAULT_DATA)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "flowphoto.db"

DEFAULT_RETENTION_SECONDS = 30 * 24 * 3600
MIN_RETENTION_SECONDS = 3600
MAX_RETENTION_SECONDS = 365 * 24 * 3600
MAX_STORAGE_BYTES = int(os.environ.get("FLOWPHOTO_MAX_STORAGE_BYTES", str(500 * 1024 * 1024)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    short_id            TEXT PRIMARY KEY,
    original_name       TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    encrypted_data      BLOB NOT NULL,
    size_bytes          INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    retention_seconds   INTEGER NOT NULL DEFAULT 2592000,
    last_accessed_at    TEXT,
    view_count          INTEGER NOT NULL DEFAULT 0,
    burn_after_read     INTEGER NOT NULL DEFAULT 0,
    link_password_hash  TEXT
);
CREATE INDEX IF NOT EXISTS idx_photos_created ON photos(created_at);
CREATE INDEX IF NOT EXISTS idx_photos_last_access ON photos(last_accessed_at);

CREATE TABLE IF NOT EXISTS vaults (
    vault_id        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT
);

CREATE TABLE IF NOT EXISTS vault_photos (
    vault_id    TEXT NOT NULL,
    short_id    TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL,
    PRIMARY KEY (vault_id, short_id)
);
CREATE INDEX IF NOT EXISTS idx_vault_photos_vault ON vault_photos(vault_id);
"""

_PHOTO_COLS = (
    "short_id", "original_name", "mime_type", "size_bytes", "created_at",
    "retention_seconds", "last_accessed_at", "view_count", "burn_after_read",
    "link_password_hash",
)


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


def _migrate_photos(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()}
    if not cols:
        return
    if "encrypted_data" not in cols:
        conn.execute("DROP TABLE photos")
        return
    migrations = {
        "retention_seconds": f"INTEGER NOT NULL DEFAULT {DEFAULT_RETENTION_SECONDS}",
        "last_accessed_at": "TEXT",
        "view_count": "INTEGER NOT NULL DEFAULT 0",
        "burn_after_read": "INTEGER NOT NULL DEFAULT 0",
        "link_password_hash": "TEXT",
    }
    for col, typedef in migrations.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col} {typedef}")


def init_db() -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos'"
        ).fetchone()
        if row:
            _migrate_photos(conn)
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


def _public_meta(photo: dict[str, Any]) -> dict[str, Any]:
    return {
        "retention_seconds": photo.get("retention_seconds") or DEFAULT_RETENTION_SECONDS,
        "last_accessed_at": photo.get("last_accessed_at"),
        "expires_at": compute_expires_at(photo),
        "view_count": int(photo.get("view_count") or 0),
        "burn_after_read": bool(photo.get("burn_after_read")),
        "has_link_password": bool(photo.get("link_password_hash")),
    }


def delete_photo(short_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM vault_photos WHERE short_id = ?", (short_id,))
        cur = conn.execute("DELETE FROM photos WHERE short_id = ?", (short_id,))
        conn.commit()
        return cur.rowcount > 0


def touch_photo_access(short_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE photos SET last_accessed_at = ? WHERE short_id = ?",
            (_utc_iso(), short_id),
        )
        conn.commit()


def get_total_storage_bytes() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS total FROM photos").fetchone()
    return int(row["total"])


def cleanup_expired_photos() -> int:
    now = _utc_now()
    deleted = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT short_id, created_at, last_accessed_at, retention_seconds FROM photos"
        ).fetchall()
        for row in rows:
            if is_photo_expired(dict(row), now):
                conn.execute("DELETE FROM vault_photos WHERE short_id = ?", (row["short_id"],))
                conn.execute("DELETE FROM photos WHERE short_id = ?", (row["short_id"],))
                deleted += 1
        conn.commit()
    return deleted


def cleanup_storage_overflow() -> int:
    """Удаляет самые старые неактивные фото при переполнении диска."""
    deleted = 0
    total = get_total_storage_bytes()
    if total <= MAX_STORAGE_BYTES:
        return 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT short_id, size_bytes, created_at, last_accessed_at, retention_seconds
            FROM photos
            ORDER BY COALESCE(last_accessed_at, created_at) ASC
            """
        ).fetchall()
        for row in rows:
            if get_total_storage_bytes() <= MAX_STORAGE_BYTES:
                break
            conn.execute("DELETE FROM vault_photos WHERE short_id = ?", (row["short_id"],))
            conn.execute("DELETE FROM photos WHERE short_id = ?", (row["short_id"],))
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
    *,
    burn_after_read: bool = False,
    link_password_hash: str | None = None,
) -> dict[str, Any]:
    created_at = _utc_iso()
    retention_seconds = clamp_retention(retention_seconds)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO photos (
                short_id, original_name, mime_type, encrypted_data, size_bytes,
                created_at, retention_seconds, last_accessed_at,
                view_count, burn_after_read, link_password_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
            """,
            (
                short_id, original_name, mime_type, encrypted_data, size_bytes,
                created_at, retention_seconds,
                1 if burn_after_read else 0,
                link_password_hash,
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
        "view_count": 0,
        "burn_after_read": burn_after_read,
        "link_password_hash": link_password_hash,
    }
    return {**photo, **_public_meta(photo)}


def _load_photo_row(short_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_PHOTO_COLS)} FROM photos WHERE short_id = ?",
            (short_id,),
        ).fetchone()
    return dict(row) if row else None


def get_photo(short_id: str, *, touch_access: bool = False) -> dict[str, Any] | None:
    photo = _load_photo_row(short_id)
    if photo is None:
        return None
    if is_photo_expired(photo):
        delete_photo(short_id)
        return None
    if touch_access:
        touch_photo_access(short_id)
        photo["last_accessed_at"] = _utc_iso()
    safe = {k: photo[k] for k in _PHOTO_COLS if k != "link_password_hash"}
    safe["link_password_hash"] = photo.get("link_password_hash")
    return {**safe, **_public_meta(photo)}


def fetch_encrypted_blob(
    short_id: str,
    *,
    link_password: str | None = None,
) -> tuple[bytes | None, str | None]:
    """
    Возвращает (blob, error).
    Увеличивает view_count, обновляет last_accessed_at.
    burn_after_read — удаляет после выдачи.
    """
    from app.security import verify_secret

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT encrypted_data, created_at, last_accessed_at, retention_seconds,
                   link_password_hash, burn_after_read, view_count
            FROM photos WHERE short_id = ?
            """,
            (short_id,),
        ).fetchone()
    if row is None:
        return None, "not_found"

    meta = dict(row)
    if is_photo_expired(meta):
        delete_photo(short_id)
        return None, "expired"

    pwd_hash = meta.get("link_password_hash")
    if pwd_hash:
        if not link_password or not verify_secret(link_password, pwd_hash):
            return None, "password_required"

    blob = row["encrypted_data"]
    burn = bool(meta.get("burn_after_read"))
    new_count = int(meta.get("view_count") or 0) + 1
    now = _utc_iso()

    with get_connection() as conn:
        if burn:
            conn.execute("DELETE FROM vault_photos WHERE short_id = ?", (short_id,))
            conn.execute("DELETE FROM photos WHERE short_id = ?", (short_id,))
        else:
            conn.execute(
                "UPDATE photos SET last_accessed_at = ?, view_count = ? WHERE short_id = ?",
                (now, new_count, short_id),
            )
        conn.commit()

    return blob, None


def entity_counts() -> tuple[int, int]:
    """(photos, vaults). Если таблиц ещё нет — (0, 0)."""
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return 0, 0
    try:
        with get_connection() as conn:
            photos = int(
                conn.execute("SELECT COUNT(*) AS c FROM photos").fetchone()["c"]
            )
            try:
                vaults = int(
                    conn.execute("SELECT COUNT(*) AS c FROM vaults").fetchone()["c"]
                )
            except sqlite3.OperationalError:
                vaults = 0
            return photos, vaults
    except sqlite3.Error:
        return 0, 0


def sqlite_row_counts_at(path: Path) -> tuple[int, int] | None:
    """Считает строки в файле БД без подмены DB_PATH. None — файл битый/пустой."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            photos = int(conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0])
            try:
                vaults = int(conn.execute("SELECT COUNT(*) FROM vaults").fetchone()[0])
            except sqlite3.OperationalError:
                vaults = 0
            return photos, vaults
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def storage_stats() -> dict[str, Any]:
    total = get_total_storage_bytes()
    photos_count, vaults_count = entity_counts()
    usage = shutil.disk_usage(DATA_DIR)
    return {
        "photos_count": photos_count,
        "vaults_count": vaults_count,
        "storage_bytes": total,
        "storage_max_bytes": MAX_STORAGE_BYTES,
        "disk_free_bytes": usage.free,
        "disk_total_bytes": usage.total,
    }