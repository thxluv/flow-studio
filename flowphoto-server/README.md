# FlowPhoto Server

Приватный обмен фото: **шифрование только в браузере** (Web Crypto API, AES-GCM 256 бит).  
Сервер хранит **только зашифрованные файлы** и минимальные метаданные в SQLite.

## Как это работает

1. Пользователь загружает фото на `/` — EXIF удаляется, файл шифруется в браузере.
2. На сервер уходит только ciphertext (IV + данные AES-GCM).
3. Сервер выдаёт короткий ID: `/view/AbCdEf123456` (12 случайных символов).
4. **Полная ссылка** для получателя:  
   `https://ваш-домен/view/AbCdEf123456#base64url-ключ-32-байта`
5. Ключ после `#` **не отправляется на сервер** (остаётся в браузере).
6. Без `#ключ` фото посмотреть нельзя. Публичного списка фото нет.

## Быстрый старт (Windows)

### 1. Python 3.10+

Скачай с https://www.python.org/downloads/ (галочка «Add to PATH»).

### 2. Установка зависимостей

```powershell
cd "путь\к\проект флов\flowphoto-server"
python -m pip install -r requirements.txt
```

### 3. Запуск

```powershell
cd flowphoto-server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Открой: **http://127.0.0.1:8000/**

### 4. FlowNote Studio

Статический FlowNote: https://thxluv.github.io/flow-studio/  
FlowPhoto: запускается локально или на VPS с HTTPS.

## API

| Метод | Путь | Описание |
|--------|------|----------|
| `GET` | `/` | Страница загрузки |
| `GET` | `/view/{short_id}` | Страница просмотра |
| `POST` | `/upload` | `encrypted_file`, `mime_type`, `original_name` |
| `GET` | `/info/{short_id}` | JSON метаданные (без ключа) |
| `GET` | `/raw/{short_id}` | Зашифрованный blob |
| `GET` | `/health` | Проверка сервера |

### Пример POST /upload

`multipart/form-data`:

- `encrypted_file` — бинарный файл (12 байт IV + ciphertext)
- `mime_type` — например `image/jpeg`
- `original_name` — имя исходного файла

Ответ:

```json
{
  "short_id": "AbCdEf123456",
  "view_path": "/view/AbCdEf123456",
  "mime_type": "image/jpeg",
  "size_bytes": 123456,
  "created_at": "2026-07-09T12:00:00+00:00"
}
```

Клиент сам добавляет `#ключ` к URL для получателя.

## Структура проекта

```
flowphoto-server/
  app/
    main.py       # FastAPI, маршруты
    database.py   # SQLite
    ids.py        # Генерация short_id
  templates/      # Jinja2: upload, view
  static/js/      # flowphoto-crypto.js
  uploads/        # Зашифрованные .bin (не в git)
  flowphoto.db    # SQLite (не в git)
  requirements.txt
```

## Безопасность

- **HTTPS обязателен в продакшене** (nginx + Let's Encrypt или Cloudflare Tunnel).
- Ключ только в hash URL — не попадает в логи сервера при обычном HTTPS.
- Сервер не может расшифровать фото без ключа.
- Лимит загрузки: **25 МБ**.
- Случайный 12-символьный ID (~58^12 комбинаций).

## Публичный доступ (для всех в интернете)

1. Задеплой на **Render.com** — в корне репозитория есть `render.yaml`.
2. Скопируй URL вида `https://flowphoto-xxxx.onrender.com`.
3. Вставь в `public-config.json` → поле `flowPhotoUrl`.
4. Запусти `deploy.bat` — FlowNote на GitHub Pages начнёт вести на облако.

Подробно: **`ПУБЛИЧНЫЙ-ЗАПУСК.txt`** в корне проекта.

## Продакшен (VPS)

1. Docker: `docker build -t flowphoto . && docker run -p 8000:8000 -v flowphoto_data:/data -e FLOWPHOTO_DATA_DIR=/data flowphoto`
2. HTTPS через nginx + Let's Encrypt.
3. Не коммить `flowphoto.db` в git.

## Отличие от старой версии

Раньше были попытки хостинга через GitHub raw / Node-сервер — **удалено**.  
Актуальная архитектура: **FastAPI + SQLite + uploads/** — как в ТЗ.

## Связь с FlowNote Studio

FlowPhoto — отдельный сервис в папке `flowphoto-server/`.  
Файл `flowphoto.html` в корне репозитория — переход на запущенный сервер.