"""Простой in-memory rate limiter для /view/ и /raw/."""
from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock

_WINDOW = int(os.environ.get("FLOWPHOTO_RATE_WINDOW", "60"))
_MAX_REQUESTS = int(os.environ.get("FLOWPHOTO_RATE_MAX", "60"))

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def _client_key(ip: str, path: str) -> str:
    return f"{ip}:{path.split('/')[1] if path.startswith('/') else path}"


def is_rate_limited(ip: str, path: str) -> bool:
    if not ip:
        return False
    now = time.time()
    key = _client_key(ip, path)
    with _lock:
        hits = _buckets[key]
        cutoff = now - _WINDOW
        _buckets[key] = [t for t in hits if t > cutoff]
        if len(_buckets[key]) >= _MAX_REQUESTS:
            return True
        _buckets[key].append(now)
    return False


def client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""