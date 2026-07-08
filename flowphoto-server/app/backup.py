"""Бэкап SQLite в S3-хранилище (Storj / R2) и restore при пустой БД."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.database import DB_PATH, DATA_DIR, entity_counts, sqlite_row_counts_at

logger = logging.getLogger("flowphoto.backup")

_BACKUP_INTERVAL = int(os.environ.get("FLOWPHOTO_BACKUP_INTERVAL", str(24 * 3600)))
_BACKUP_KEEP = int(os.environ.get("FLOWPHOTO_BACKUP_KEEP", "12"))
_AUTO_DEBOUNCE_SEC = int(os.environ.get("FLOWPHOTO_BACKUP_AUTO_DEBOUNCE", "60"))
_AUTO_MIN_GAP_SEC = int(os.environ.get("FLOWPHOTO_BACKUP_AUTO_MIN_GAP", "45"))

_last_backup_at: str | None = None
_auto_pending = False
_auto_timer: threading.Timer | None = None
_auto_lock = threading.Lock()
_last_run_mono = 0.0


def backup_configured() -> bool:
    return bool(
        os.environ.get("FLOWPHOTO_BACKUP_BUCKET")
        and os.environ.get("FLOWPHOTO_BACKUP_ACCESS_KEY")
        and os.environ.get("FLOWPHOTO_BACKUP_SECRET_KEY")
    )


def backup_status() -> dict:
    return {
        "configured": backup_configured(),
        "interval_sec": _BACKUP_INTERVAL,
        "auto_debounce_sec": _AUTO_DEBOUNCE_SEC,
        "auto_pending": _auto_pending,
        "last_upload_at": _last_backup_at,
    }


def schedule_auto_backup(reason: str = "change") -> None:
    """Фоновый бэкап в Storj через debounce после изменений в БД."""
    global _auto_timer, _auto_pending
    if not backup_configured():
        return
    photos, vaults = entity_counts()
    if not _has_meaningful_data(photos, vaults):
        return
    with _auto_lock:
        _auto_pending = True
        if _auto_timer is not None:
            _auto_timer.cancel()
        _auto_timer = threading.Timer(_AUTO_DEBOUNCE_SEC, _fire_auto_backup, args=(reason,))
        _auto_timer.daemon = True
        _auto_timer.start()
    logger.info("Auto backup scheduled in %ss (%s)", _AUTO_DEBOUNCE_SEC, reason)


def _fire_auto_backup(reason: str) -> None:
    global _auto_pending, _last_backup_at, _last_run_mono, _auto_timer
    with _auto_lock:
        _auto_pending = False
        _auto_timer = None
    if time.monotonic() - _last_run_mono < _AUTO_MIN_GAP_SEC:
        logger.info("Auto backup skipped (cooldown, %s)", reason)
        return
    if _run_backup_inner():
        _last_run_mono = time.monotonic()
        logger.info("Auto backup completed (%s)", reason)


def _s3_client():
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("FLOWPHOTO_BACKUP_ENDPOINT") or None
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["FLOWPHOTO_BACKUP_ACCESS_KEY"],
        aws_secret_access_key=os.environ["FLOWPHOTO_BACKUP_SECRET_KEY"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def _backup_prefix() -> str:
    return os.environ.get("FLOWPHOTO_BACKUP_PREFIX", "flowphoto/").rstrip("/")


def _has_meaningful_data(photos: int, vaults: int) -> bool:
    return photos > 0 or vaults > 0


def _db_needs_restore() -> bool:
    """Восстанавливать, если БД нет или в ней нет ни фото, ни аккаунтов Vault."""
    if not DB_PATH.exists():
        return True
    try:
        if DB_PATH.stat().st_size == 0:
            return True
    except OSError:
        return True
    photos, vaults = entity_counts()
    return not _has_meaningful_data(photos, vaults)


def _head_metadata(client, bucket: str, key: str) -> tuple[int, int]:
    """(photos, vaults) из S3 Metadata, (-1,-1) если нет."""
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata") or {}
        if "photos" in meta and "vaults" in meta:
            return int(meta["photos"]), int(meta["vaults"])
    except Exception:
        pass
    return -1, -1


def _list_backup_objects(client, bucket: str, prefix: str) -> list[dict]:
    """Все .db в префиксе, новые первыми."""
    full_prefix = f"{prefix}/" if prefix else ""
    entries: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key.endswith(".db"):
                continue
            mp, mv = _head_metadata(client, bucket, key)
            entries.append(
                {
                    "key": key,
                    "modified": obj.get("LastModified"),
                    "size": int(obj.get("Size") or 0),
                    "meta_photos": mp,
                    "meta_vaults": mv,
                }
            )
    entries.sort(
        key=lambda x: x["modified"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return entries


def _snapshot_db(dest: Path) -> tuple[int, int]:
    """Консистентная копия SQLite (включая WAL). Возвращает (photos, vaults)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    counts = sqlite_row_counts_at(dest)
    if counts is None:
        return 0, 0
    return counts


def _try_restore_key(client, bucket: str, key: str) -> tuple[bool, int, int]:
    tmp = DATA_DIR / "_restore_tmp.db"
    try:
        if tmp.exists():
            tmp.unlink()
        client.download_file(bucket, key, str(tmp))
        if tmp.stat().st_size == 0:
            return False, 0, 0
        counts = sqlite_row_counts_at(tmp)
        if counts is None:
            return False, 0, 0
        photos, vaults = counts
        if DB_PATH.exists():
            DB_PATH.unlink()
        shutil.move(str(tmp), str(DB_PATH))
        logger.info(
            "Restored database from s3://%s/%s (photos=%s, vaults=%s)",
            bucket,
            key,
            photos,
            vaults,
        )
        return True, photos, vaults
    except Exception as exc:
        logger.warning("Failed to restore %s: %s", key, exc)
        return False, 0, 0
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def restore_latest_backup_if_needed() -> bool:
    """Скачивает лучший .db из S3, если локально нет аккаунтов/фото."""
    if not backup_configured():
        return False
    if not _db_needs_restore():
        photos, vaults = entity_counts()
        logger.info("Skip restore: local DB has data (photos=%s, vaults=%s)", photos, vaults)
        return False

    try:
        client = _s3_client()
        bucket = os.environ["FLOWPHOTO_BACKUP_BUCKET"]
        prefix = _backup_prefix()
        objects = _list_backup_objects(client, bucket, prefix)
        if not objects:
            logger.warning("No backup objects found in s3://%s/%s", bucket, prefix)
            return False

        # Перебираем от новых к старым — берём первый бэкап с аккаунтом или фото
        for obj in objects:
            key = obj["key"]
            mp, mv = obj["meta_photos"], obj["meta_vaults"]
            if mp >= 0 and mv >= 0 and not _has_meaningful_data(mp, mv):
                continue
            ok, photos, vaults = _try_restore_key(client, bucket, key)
            if ok and _has_meaningful_data(photos, vaults):
                return True
            if DB_PATH.exists():
                DB_PATH.unlink(missing_ok=True)

        # Все бэкапы пустые — подтянуть хотя бы последний (схема)
        ok, _, _ = _try_restore_key(client, bucket, objects[0]["key"])
        return ok
    except Exception as exc:
        logger.exception("Restore failed: %s", exc)
        return False


def _prune_old_backups(client, bucket: str, prefix: str, keep: int) -> None:
    if keep <= 0:
        return
    full_prefix = f"{prefix}/" if prefix else ""
    entries: list[tuple[datetime | None, str]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if key.endswith(".db"):
                entries.append((obj.get("LastModified"), key))
    entries.sort(
        key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    for _, key in entries[keep:]:
        try:
            client.delete_object(Bucket=bucket, Key=key)
            logger.info("Pruned old backup: s3://%s/%s", bucket, key)
        except Exception as exc:
            logger.warning("Failed to prune %s: %s", key, exc)


def _run_backup_inner() -> bool:
    global _last_backup_at
    if not backup_configured():
        return False
    if not DB_PATH.exists():
        logger.warning("DB not found: %s", DB_PATH)
        return False

    photos, vaults = entity_counts()
    if not _has_meaningful_data(photos, vaults):
        logger.info("Skip backup: database empty (no photos or vault accounts)")
        return False

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = DATA_DIR / f"flowphoto_backup_{stamp}.db"
    try:
        snap_photos, snap_vaults = _snapshot_db(tmp)
        bucket = os.environ["FLOWPHOTO_BACKUP_BUCKET"]
        prefix = _backup_prefix()
        key = f"{prefix}/flowphoto_{stamp}.db"
        client = _s3_client()
        client.upload_file(
            str(tmp),
            bucket,
            key,
            ExtraArgs={
                "Metadata": {
                    "photos": str(snap_photos),
                    "vaults": str(snap_vaults),
                }
            },
        )
        _prune_old_backups(client, bucket, prefix, _BACKUP_KEEP)
        _last_backup_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Backup uploaded: s3://%s/%s (photos=%s, vaults=%s)",
            bucket,
            key,
            snap_photos,
            snap_vaults,
        )
        return True
    except Exception as exc:
        logger.exception("Backup failed: %s", exc)
        return False
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def run_backup() -> bool:
    ok = _run_backup_inner()
    if ok:
        global _last_run_mono
        _last_run_mono = time.monotonic()
    return ok