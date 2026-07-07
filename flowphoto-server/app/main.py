"""
FlowPhoto Server — публичный приватный обмен фото.

Шифрование только в браузере (AES-GCM 256). Сервер хранит ciphertext в SQLite.
Ключ — только в hash ссылки (#...), на сервер не передаётся.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import (
    DATA_DIR,
    DEFAULT_RETENTION_SECONDS,
    MAX_RETENTION_SECONDS,
    MIN_RETENTION_SECONDS,
    cleanup_expired_photos,
    clamp_retention,
    get_encrypted_blob,
    get_photo,
    init_db,
    insert_photo,
)
from app.ids import generate_short_id, is_valid_short_id

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 МБ
CLEANUP_INTERVAL_SECONDS = 3600  # каждый час

# Сайт FlowNote на GitHub Pages — для CORS (если понадобится API с другого origin)
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
    version="2.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            cleanup_expired_photos()
        except Exception:
            pass


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    cleanup_expired_photos()
    asyncio.create_task(_periodic_cleanup())


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "max_mb": MAX_FILE_BYTES // (1024 * 1024),
            "default_retention_seconds": DEFAULT_RETENTION_SECONDS,
            "min_retention_seconds": MIN_RETENTION_SECONDS,
            "max_retention_seconds": MAX_RETENTION_SECONDS,
            "flownote_url": os.environ.get(
                "FLOWNOTE_PUBLIC_URL",
                "https://thxluv.github.io/flow-studio/index.html",
            ),
        },
    )


@app.get("/view/{short_id}", response_class=HTMLResponse)
async def view_page(request: Request, short_id: str) -> HTMLResponse:
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Неверный формат ссылки")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(
            status_code=404,
            detail="Фото не найдено или срок хранения истёк",
        )
    return templates.TemplateResponse(
        "view.html",
        {"request": request, "short_id": short_id, "photo": photo},
    )


@app.post("/upload")
async def upload_encrypted(
    encrypted_file: UploadFile = File(...),
    mime_type: str = Form(...),
    original_name: str = Form("photo.jpg"),
    retention_seconds: int = Form(DEFAULT_RETENTION_SECONDS),
):
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Разрешены только image/*")

    retention_seconds = clamp_retention(retention_seconds)

    short_id = generate_short_id()
    for _ in range(5):
        if get_photo(short_id) is None:
            break
        short_id = generate_short_id()
    else:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать ID")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await encrypted_file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ",
            )
        chunks.append(chunk)

    payload = b"".join(chunks)
    if len(payload) < 13:
        raise HTTPException(status_code=400, detail="Слишком маленький зашифрованный файл")

    safe_name = (original_name or "photo.jpg")[:255]
    meta = insert_photo(
        short_id=short_id,
        original_name=safe_name,
        mime_type=mime_type,
        encrypted_data=payload,
        size_bytes=len(payload),
        retention_seconds=retention_seconds,
    )

    return JSONResponse(
        {
            "short_id": short_id,
            "view_path": f"/view/{short_id}",
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
            "created_at": meta["created_at"],
            "retention_seconds": meta["retention_seconds"],
            "expires_at": meta["expires_at"],
        }
    )


@app.get("/info/{short_id}")
async def photo_info(short_id: str):
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Не найдено или срок хранения истёк")
    return {
        "short_id": photo["short_id"],
        "original_name": photo["original_name"],
        "mime_type": photo["mime_type"],
        "size_bytes": photo["size_bytes"],
        "created_at": photo["created_at"],
        "retention_seconds": photo["retention_seconds"],
        "last_accessed_at": photo["last_accessed_at"],
        "expires_at": photo["expires_at"],
        "encrypted": True,
    }


@app.get("/raw/{short_id}")
async def raw_encrypted(short_id: str):
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    blob = get_encrypted_blob(short_id, touch_access=True)
    if blob is None:
        raise HTTPException(status_code=404, detail="Не найдено или срок хранения истёк")
    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "flowphoto",
        "version": "2.2.0",
        "data_dir": str(DATA_DIR),
        "retention": {
            "default_seconds": DEFAULT_RETENTION_SECONDS,
            "min_seconds": MIN_RETENTION_SECONDS,
            "max_seconds": MAX_RETENTION_SECONDS,
        },
        "public": True,
    }