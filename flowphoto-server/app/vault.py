"""Опциональная библиотека FlowPhoto Vault — один пароль, без email."""
from __future__ import annotations

import secrets
from typing import Any

from app.database import get_connection, get_photo, _utc_iso
from app.security import create_vault_token, hash_secret, verify_secret, verify_vault_token

_MAX_VAULT_PHOTOS = 200


def _generate_vault_id() -> str:
    return secrets.token_hex(8)


def login_or_create(password: str) -> dict[str, Any] | None:
    from app.security import hash_secret as hs

    pwd_hash = hs(password)
    with get_connection() as conn:
        rows = conn.execute("SELECT vault_id, password_hash FROM vaults").fetchall()
        for row in rows:
            if verify_secret(password, row["password_hash"]):
                conn.execute(
                    "UPDATE vaults SET last_login_at = ? WHERE vault_id = ?",
                    (_utc_iso(), row["vault_id"]),
                )
                conn.commit()
                return {
                    "vault_id": row["vault_id"],
                    "token": create_vault_token(row["vault_id"]),
                    "created": False,
                }
        vault_id = _generate_vault_id()
        now = _utc_iso()
        conn.execute(
            "INSERT INTO vaults (vault_id, password_hash, created_at, last_login_at) VALUES (?, ?, ?, ?)",
            (vault_id, pwd_hash, now, now),
        )
        conn.commit()
        return {
            "vault_id": vault_id,
            "token": create_vault_token(vault_id),
            "created": True,
        }


def resolve_token(token: str | None) -> str | None:
    return verify_vault_token(token or "")


def add_photo_to_vault(vault_id: str, short_id: str, label: str = "") -> bool:
    if get_photo(short_id) is None:
        return False
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM vault_photos WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()["c"]
        if count >= _MAX_VAULT_PHOTOS:
            return False
        conn.execute(
            """
            INSERT OR IGNORE INTO vault_photos (vault_id, short_id, label, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (vault_id, short_id, (label or "")[:128], _utc_iso()),
        )
        conn.commit()
        return True


def list_vault_photos(vault_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT short_id, label, added_at
            FROM vault_photos
            WHERE vault_id = ?
            ORDER BY added_at DESC
            """,
            (vault_id,),
        ).fetchall()
    out = []
    for row in rows:
        photo = get_photo(row["short_id"])
        if photo is None:
            continue
        out.append({
            "short_id": row["short_id"],
            "label": row["label"],
            "added_at": row["added_at"],
            "original_name": photo["original_name"],
            "size_bytes": photo["size_bytes"],
            "view_count": photo.get("view_count", 0),
            "burn_after_read": bool(photo.get("burn_after_read")),
            "expires_at": photo.get("expires_at"),
            "view_path": f"/view/{row['short_id']}",
        })
    return out


def remove_from_vault(vault_id: str, short_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM vault_photos WHERE vault_id = ? AND short_id = ?",
            (vault_id, short_id),
        )
        conn.commit()
        return cur.rowcount > 0