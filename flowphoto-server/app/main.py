"""
FlowPhoto Server — публичный приватный обмен фото.

Шифрование только в браузере (AES-GCM 256). Сервер хранит ciphertext в SQLite.
Ключ — только в hash ссылки (#...), на сервер не передаётся.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.backup import _BACKUP_INTERVAL, backup_configured, run_backup
from app.database import (
    DATA_DIR,
    DEFAULT_RETENTION_SECONDS,
    MAX_RETENTION_SECONDS,
    MAX_STORAGE_BYTES,
    MIN_RETENTION_SECONDS,
    cleanup_expired_photos,
    cleanup_storage_overflow,
    clamp_retention,
    fetch_encrypted_blob,
    get_photo,
    init_db,
    insert_photo,
    storage_stats,
)
from app.ids import generate_short_id, is_valid_short_id
from app.rate_limit import client_ip, is_rate_limited
from app.security import hash_secret
from app import vault as vault_mod

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

MAX_FILE_BYTES = 25 * 1024 * 1024
CLEANUP_INTERVAL_SECONDS = 3600

DEFAULT_ORIGINS = [
    "https://thxluv.github.io",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
_extra = os.environ.get("FLOWPHOTO_CORS_ORIGINS", "")
CORS_ORIGINS = DEFAULT_ORIGINS + [o.strip() for o in _extra.split(",") if o.strip()]

app = FastAPI(
    title="FlowPhoto",
    description="Приватный обмен фото: шифрование в браузере, сервер хранит только ciphertext",
    version="3.3.0",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/raw/") or path.startswith("/view/"):
            ip = client_ip(request)
            if is_rate_limited(ip, path):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Слишком много запросов — подожди минуту"},
                )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _flownote_url() -> str:
    return os.environ.get(
        "FLOWNOTE_PUBLIC_URL",
        "https://thxluv.github.io/flow-studio/index.html",
    )


def _template_ctx(request: Request, **extra) -> dict:
    return {
        "request": request,
        "max_mb": MAX_FILE_BYTES // (1024 * 1024),
        "default_retention_seconds": DEFAULT_RETENTION_SECONDS,
        "min_retention_seconds": MIN_RETENTION_SECONDS,
        "max_retention_seconds": MAX_RETENTION_SECONDS,
        "flownote_url": _flownote_url(),
        **extra,
    }


def _photo_json(photo: dict) -> dict:
    return {
        "short_id": photo["short_id"],
        "original_name": photo["original_name"],
        "mime_type": photo["mime_type"],
        "size_bytes": photo["size_bytes"],
        "created_at": photo["created_at"],
        "retention_seconds": photo["retention_seconds"],
        "last_accessed_at": photo["last_accessed_at"],
        "expires_at": photo["expires_at"],
        "view_count": photo.get("view_count", 0),
        "burn_after_read": photo.get("burn_after_read", False),
        "has_link_password": photo.get("has_link_password", False),
        "encrypted": True,
    }


async def _read_upload(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _periodic_tasks() -> None:
    backup_counter = 0
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            cleanup_expired_photos()
            cleanup_storage_overflow()
            backup_counter += CLEANUP_INTERVAL_SECONDS
            if backup_configured() and backup_counter >= _BACKUP_INTERVAL:
                run_backup()
                backup_counter = 0
        except Exception:
            pass


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    cleanup_expired_photos()
    cleanup_storage_overflow()
    if backup_configured():
        asyncio.create_task(asyncio.to_thread(run_backup))
    asyncio.create_task(_periodic_tasks())


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("upload.html", _template_ctx(request, active_nav="upload"))


@app.get("/vault", response_class=HTMLResponse)
async def vault_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("vault.html", _template_ctx(request, active_nav="vault"))


@app.get("/view/{short_id}", response_class=HTMLResponse)
async def view_page(request: Request, short_id: str) -> HTMLResponse:
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Неверный формат ссылки")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото не найдено или срок хранения истёк")
    return templates.TemplateResponse(
        "view.html",
        _template_ctx(request, short_id=short_id, photo=photo),
    )


@app.post("/upload")
async def upload_encrypted(
    encrypted_file: UploadFile = File(...),
    mime_type: str = Form(...),
    original_name: str = Form("photo.jpg"),
    retention_seconds: int = Form(DEFAULT_RETENTION_SECONDS),
    burn_after_read: str = Form("0"),
    link_password: str = Form(""),
    x_vault_token: str | None = Header(default=None),
    x_vault_upload_claim: str | None = Header(default=None),
):
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Разрешены только image/*")

    retention_seconds = clamp_retention(retention_seconds)
    is_burn = burn_after_read in ("1", "true", "True", "yes")
    pwd_hash = None
    if link_password and link_password.strip():
        try:
            pwd_hash = hash_secret(link_password.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный пароль ссылки")

    short_id = generate_short_id()
    for _ in range(5):
        if get_photo(short_id) is None:
            break
        short_id = generate_short_id()
    else:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать ID")

    payload = await _read_upload(encrypted_file)
    if len(payload) < 13:
        raise HTTPException(status_code=400, detail="Слишком маленький зашифрованный файл")

    if storage_stats()["storage_bytes"] + len(payload) > MAX_STORAGE_BYTES:
        cleanup_expired_photos()
        cleanup_storage_overflow()
        if storage_stats()["storage_bytes"] + len(payload) > MAX_STORAGE_BYTES:
            raise HTTPException(status_code=507, detail="Хранилище сервера заполнено")

    safe_name = (original_name or "photo.jpg")[:255]
    meta = insert_photo(
        short_id=short_id,
        original_name=safe_name,
        mime_type=mime_type,
        encrypted_data=payload,
        size_bytes=len(payload),
        retention_seconds=retention_seconds,
        burn_after_read=is_burn,
        link_password_hash=pwd_hash,
    )

    vault_id = vault_mod.resolve_token(x_vault_token)
    in_vault = False
    if vault_id and vault_mod.can_upload_to_vault(vault_id, x_vault_upload_claim):
        in_vault = vault_mod.add_photo_to_vault(vault_id, short_id, safe_name)

    return JSONResponse(
        {
            "short_id": short_id,
            "view_path": f"/view/{short_id}",
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
            "created_at": meta["created_at"],
            "retention_seconds": meta["retention_seconds"],
            "expires_at": meta["expires_at"],
            "burn_after_read": meta["burn_after_read"],
            "has_link_password": meta["has_link_password"],
            "in_vault": in_vault,
        }
    )


@app.get("/info/{short_id}")
async def photo_info(short_id: str):
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Не найдено или срок хранения истёк")
    return _photo_json(photo)


@app.get("/raw/{short_id}")
async def raw_encrypted_get(short_id: str):
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Не найдено или срок хранения истёк")
    if photo.get("has_link_password"):
        raise HTTPException(status_code=401, detail="Нужен пароль ссылки — используй POST /raw")
    blob, err = fetch_encrypted_blob(short_id)
    return _raw_response(blob, err)


@app.post("/raw/{short_id}")
async def raw_encrypted_post(short_id: str, link_password: str = Form("")):
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    blob, err = fetch_encrypted_blob(short_id, link_password=link_password or None)
    return _raw_response(blob, err)


def _raw_response(blob: bytes | None, err: str | None) -> Response:
    if err == "password_required":
        raise HTTPException(status_code=403, detail="Неверный пароль ссылки")
    if err in ("not_found", "expired") or blob is None:
        raise HTTPException(status_code=404, detail="Не найдено или срок хранения истёк")
    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.post("/api/vault/check")
async def vault_check_password(password: str = Form(...)):
    if len(password.strip()) < 4:
        return {"exists": False}
    return {"exists": vault_mod.password_exists(password.strip())}


@app.post("/api/vault/login")
async def vault_login(password: str = Form(...), intent: str = Form("auto")):
    if len(password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Пароль минимум 4 символа")
    result = vault_mod.login_or_create(password.strip(), intent=intent.strip() or "auto")
    if result is None:
        raise HTTPException(status_code=500, detail="Ошибка FlowVault")
    if result.get("error") == "password_taken":
        raise HTTPException(
            status_code=409,
            detail="Этот пароль уже занят — выберите другой для нового FlowVault",
        )
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="FlowVault с таким паролем не найден")
    return result


@app.get("/api/vault/me")
async def vault_me(x_vault_token: str | None = Header(default=None)):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return {"vault_id": vault_id}


@app.get("/api/vault/photos")
async def vault_photos(x_vault_token: str | None = Header(default=None)):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    return {"photos": vault_mod.list_vault_photos(vault_id)}


@app.post("/api/vault/photos/{short_id}")
async def vault_add_photo(
    short_id: str,
    x_vault_token: str | None = Header(default=None),
    label: str = Form(""),
):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=400, detail="Неверный ID")
    if not vault_mod.add_photo_to_vault(vault_id, short_id, label):
        raise HTTPException(status_code=400, detail="Не удалось добавить")
    return {"ok": True}


@app.delete("/api/vault/photos/{short_id}")
async def vault_delete_photo(
    short_id: str,
    x_vault_token: str | None = Header(default=None),
    x_vault_upload_claim: str | None = Header(default=None),
):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=400, detail="Неверный ID")
    if not vault_mod.delete_vault_photo_permanent(vault_id, short_id, x_vault_upload_claim):
        raise HTTPException(status_code=403, detail="Нет прав или фото не найдено")
    return {"ok": True, "deleted": short_id}


@app.post("/api/vault/photos/delete-batch")
async def vault_delete_batch(
    short_ids: str = Form(...),
    x_vault_token: str | None = Header(default=None),
    x_vault_upload_claim: str | None = Header(default=None),
):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    ids = [s.strip() for s in short_ids.split(",") if s.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Не выбрано ни одного фото")
    deleted = vault_mod.delete_vault_photos_batch(vault_id, ids, x_vault_upload_claim)
    if deleted == 0:
        raise HTTPException(status_code=403, detail="Нет прав на удаление")
    return {"ok": True, "deleted_count": deleted}


@app.post("/api/vault/burn-all")
async def vault_burn_all(
    x_vault_token: str | None = Header(default=None),
    x_vault_upload_claim: str | None = Header(default=None),
):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    deleted = vault_mod.burn_all_vault_photos(vault_id, x_vault_upload_claim)
    if deleted == 0 and vault_mod.list_vault_photos(vault_id):
        raise HTTPException(status_code=403, detail="Нет прав на удаление")
    return {"ok": True, "deleted_count": deleted}


@app.delete("/api/vault/account")
async def vault_delete_account(
    password: str = Form(...),
    x_vault_token: str | None = Header(default=None),
    x_vault_upload_claim: str | None = Header(default=None),
):
    vault_id = vault_mod.resolve_token(x_vault_token)
    if not vault_id:
        raise HTTPException(status_code=401, detail="Нужен вход в FlowVault")
    if not vault_mod.delete_vault_account(vault_id, password.strip(), x_vault_upload_claim):
        raise HTTPException(status_code=403, detail="Неверный пароль или нет прав")
    return {"ok": True, "deleted": True}


@app.get("/health")
async def health():
    stats = storage_stats()
    return {
        "status": "ok",
        "service": "flowphoto",
        "version": "3.3.0",
        "data_dir": str(DATA_DIR),
        "retention": {
            "default_seconds": DEFAULT_RETENTION_SECONDS,
            "min_seconds": MIN_RETENTION_SECONDS,
            "max_seconds": MAX_RETENTION_SECONDS,
        },
        "storage": stats,
        "backup_configured": backup_configured(),
        "public": True,
    }