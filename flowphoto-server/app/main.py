"""
FlowPhoto Server — FastAPI backend для приватного обмена фото.

Сервер хранит ТОЛЬКО зашифрованные файлы и метаданные.
Ключ расшифровки передаётся только в hash-фрагменте ссылки (#...) на клиенте.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import get_photo, init_db, insert_photo
from app.ids import generate_short_id, is_valid_short_id

# --- Пути ---
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 МБ

app = FastAPI(
    title="FlowPhoto",
    description="Приватный обмен фото: шифрование в браузере, сервер хранит только ciphertext",
    version="2.0.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Страницы (Jinja2)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request) -> HTMLResponse:
    """Главная: загрузка фото с drag & drop."""
    return templates.TemplateResponse(
        "upload.html",
        {"request": request, "max_mb": MAX_FILE_BYTES // (1024 * 1024)},
    )


@app.get("/view/{short_id}", response_class=HTMLResponse)
async def view_page(request: Request, short_id: str) -> HTMLResponse:
    """Страница просмотра: JS берёт ключ из #hash и расшифровывает в браузере."""
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Неверный формат ссылки")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    return templates.TemplateResponse(
        "view.html",
        {"request": request, "short_id": short_id, "photo": photo},
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/upload")
async def upload_encrypted(
    encrypted_file: UploadFile = File(..., description="IV (12 байт) + AES-GCM ciphertext"),
    mime_type: str = Form(...),
    original_name: str = Form("photo.jpg"),
):
    """
    Принимает уже зашифрованный файл с клиента.
    Ключ на сервер НЕ передаётся.
    """
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Разрешены только image/*")

    # Уникальный ID (коллизии практически исключены)
    short_id = generate_short_id()
    for _ in range(5):
        if get_photo(short_id) is None:
            break
        short_id = generate_short_id()
    else:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать ID")

    dest = UPLOADS_DIR / f"{short_id}.bin"
    total = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await encrypted_file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Ошибка записи файла") from exc

    if total < 13:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Слишком маленький зашифрованный файл")

    safe_name = (original_name or "photo.jpg")[:255]
    meta = insert_photo(
        short_id=short_id,
        original_name=safe_name,
        mime_type=mime_type,
        file_path=str(dest.relative_to(BASE_DIR)),
        size_bytes=total,
    )

    return JSONResponse(
        {
            "short_id": short_id,
            "view_path": f"/view/{short_id}",
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
            "created_at": meta["created_at"],
        }
    )


@app.get("/info/{short_id}")
async def photo_info(short_id: str):
    """Публичные метаданные без ключа и без расшифрованного содержимого."""
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Не найдено")
    return {
        "short_id": photo["short_id"],
        "original_name": photo["original_name"],
        "mime_type": photo["mime_type"],
        "size_bytes": photo["size_bytes"],
        "created_at": photo["created_at"],
        "encrypted": True,
    }


@app.get("/raw/{short_id}")
async def raw_encrypted(short_id: str):
    """Отдаёт зашифрованный blob (IV + ciphertext). Без ключа бесполезен."""
    if not is_valid_short_id(short_id):
        raise HTTPException(status_code=404, detail="Не найдено")
    photo = get_photo(short_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Не найдено")

    path = BASE_DIR / photo["file_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл отсутствует на диске")

    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "flowphoto"}