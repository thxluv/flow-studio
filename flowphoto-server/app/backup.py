"""Ежедневный бэкап SQLite в S3-совместимое хранилище (AWS S3 / Cloudflare R2)."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.database import DB_PATH, DATA_DIR

logger = logging.getLogger("flowphoto.backup")

_BACKUP_INTERVAL = int(os.environ.get("FLOWPHOTO_BACKUP_INTERVAL", str(24 * 3600)))


def backup_configured() -> bool:
    return bool(
        os.environ.get("FLOWPHOTO_BACKUP_BUCKET")
        and os.environ.get("FLOWPHOTO_BACKUP_ACCESS_KEY")
        and os.environ.get("FLOWPHOTO_BACKUP_SECRET_KEY")
    )


def run_backup() -> bool:
    if not backup_configured():
        return False
    if not DB_PATH.exists():
        logger.warning("DB not found: %s", DB_PATH)
        return False

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.error("boto3 not installed — backup skipped")
        return False

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = DATA_DIR / f"flowphoto_backup_{stamp}.db"
    try:
        shutil.copy2(DB_PATH, tmp)
        endpoint = os.environ.get("FLOWPHOTO_BACKUP_ENDPOINT") or None
        bucket = os.environ["FLOWPHOTO_BACKUP_BUCKET"]
        prefix = os.environ.get("FLOWPHOTO_BACKUP_PREFIX", "flowphoto/").rstrip("/")
        key = f"{prefix}/flowphoto_{stamp}.db"

        session = boto3.session.Session()
        client = session.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ["FLOWPHOTO_BACKUP_ACCESS_KEY"],
            aws_secret_access_key=os.environ["FLOWPHOTO_BACKUP_SECRET_KEY"],
            config=Config(signature_version="s3v4"),
        )
        client.upload_file(str(tmp), bucket, key)
        logger.info("Backup uploaded: s3://%s/%s", bucket, key)
        return True
    except Exception as exc:
        logger.exception("Backup failed: %s", exc)
        return False
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)