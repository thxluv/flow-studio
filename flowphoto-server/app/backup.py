"""Бэкап SQLite в S3/R2 и восстановление при пустой БД (для Free-tier survival)."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.database import DB_PATH, DATA_DIR

logger = logging.getLogger("flowphoto.backup")

_BACKUP_INTERVAL = int(os.environ.get("FLOWPHOTO_BACKUP_INTERVAL", str(24 * 3600)))
_BACKUP_KEEP = int(os.environ.get("FLOWPHOTO_BACKUP_KEEP", "12"))


def backup_configured() -> bool:
    return bool(
        os.environ.get("FLOWPHOTO_BACKUP_BUCKET")
        and os.environ.get("FLOWPHOTO_BACKUP_ACCESS_KEY")
        and os.environ.get("FLOWPHOTO_BACKUP_SECRET_KEY")
    )


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
        config=Config(signature_version="s3v4"),
    )


def _backup_prefix() -> str:
    return os.environ.get("FLOWPHOTO_BACKUP_PREFIX", "flowphoto/").rstrip("/")


def _db_needs_restore() -> bool:
    if not DB_PATH.exists():
        return True
    try:
        return DB_PATH.stat().st_size == 0
    except OSError:
        return True


def _latest_backup_key(client, bucket: str, prefix: str) -> str | None:
    paginator = client.get_paginator("list_objects_v2")
    latest_key = None
    latest_time = None
    full_prefix = f"{prefix}/" if prefix else ""
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key.endswith(".db"):
                continue
            modified = obj.get("LastModified")
            if latest_time is None or (modified and modified > latest_time):
                latest_time = modified
                latest_key = key
    return latest_key


def restore_latest_backup_if_needed() -> bool:
    """Скачивает последний .db из R2/S3, если локальная БД пуста или отсутствует."""
    if not backup_configured():
        return False
    if not _db_needs_restore():
        return False

    try:
        client = _s3_client()
        bucket = os.environ["FLOWPHOTO_BACKUP_BUCKET"]
        prefix = _backup_prefix()
        key = _latest_backup_key(client, bucket, prefix)
        if not key:
            logger.warning("No backup objects found in s3://%s/%s", bucket, prefix)
            return False

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = DATA_DIR / "_restore_tmp.db"
        client.download_file(bucket, key, str(tmp))
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return False
        shutil.move(str(tmp), str(DB_PATH))
        logger.info("Restored database from s3://%s/%s", bucket, key)
        return True
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
    entries.sort(key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for _, key in entries[keep:]:
        try:
            client.delete_object(Bucket=bucket, Key=key)
            logger.info("Pruned old backup: s3://%s/%s", bucket, key)
        except Exception as exc:
            logger.warning("Failed to prune %s: %s", key, exc)


def run_backup() -> bool:
    if not backup_configured():
        return False
    if not DB_PATH.exists():
        logger.warning("DB not found: %s", DB_PATH)
        return False

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = DATA_DIR / f"flowphoto_backup_{stamp}.db"
    try:
        shutil.copy2(DB_PATH, tmp)
        bucket = os.environ["FLOWPHOTO_BACKUP_BUCKET"]
        prefix = _backup_prefix()
        key = f"{prefix}/flowphoto_{stamp}.db"
        client = _s3_client()
        client.upload_file(str(tmp), bucket, key)
        _prune_old_backups(client, bucket, prefix, _BACKUP_KEEP)
        logger.info("Backup uploaded: s3://%s/%s", bucket, key)
        return True
    except Exception as exc:
        logger.exception("Backup failed: %s", exc)
        return False
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)