"""Хеширование паролей (stdlib PBKDF2) и подпись vault-токенов."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any

_PBKDF2_ITERATIONS = 600_000
_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 дней


def _vault_secret() -> bytes:
    raw = os.environ.get("FLOWPHOTO_VAULT_SECRET", "flowphoto-dev-change-me-in-production")
    return raw.encode("utf-8")


def hash_secret(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Пустой пароль")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.strip().encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_secret(value: str, stored: str) -> bool:
    if not value or not stored:
        return False
    try:
        algo, iterations, salt, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        it = int(iterations)
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            value.strip().encode("utf-8"),
            salt.encode("utf-8"),
            it,
        ).hex()
        return hmac.compare_digest(expected, digest_hex)
    except (ValueError, TypeError):
        return False


def create_vault_token(vault_id: str) -> str:
    issued = int(time.time())
    payload = f"{vault_id}:{issued}"
    sig = hmac.new(_vault_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def create_upload_claim(vault_id: str) -> str:
    """Выдаётся только при создании Vault — право загружать в библиотеку."""
    issued = int(time.time())
    payload = f"upload:{vault_id}:{issued}"
    sig = hmac.new(_vault_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_upload_claim(vault_id: str, claim: str) -> bool:
    if not vault_id or not claim:
        return False
    try:
        pad = "=" * (-len(claim) % 4)
        raw = base64.urlsafe_b64decode((claim + pad).encode("ascii")).decode("utf-8")
        body, sig = raw.rsplit(":", 1)
        if not body.startswith("upload:"):
            return False
        _, claim_vault, issued_str = body.split(":", 2)
        if claim_vault != vault_id:
            return False
        if int(time.time()) - int(issued_str) > _TOKEN_TTL_SECONDS:
            return False
        expected = hmac.new(_vault_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except (ValueError, TypeError, UnicodeDecodeError):
        return False


def verify_vault_token(token: str) -> str | None:
    if not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii")).decode("utf-8")
        vault_id, issued_str, sig = raw.rsplit(":", 2)
        payload = f"{vault_id}:{issued_str}"
        expected = hmac.new(_vault_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        if int(time.time()) - int(issued_str) > _TOKEN_TTL_SECONDS:
            return None
        if not vault_id or len(vault_id) != 16:
            return None
        return vault_id
    except (ValueError, TypeError, UnicodeDecodeError):
        return None