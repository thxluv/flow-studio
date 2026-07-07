# Flow Studio

Экосистема приватных инструментов **Flow** — zero-knowledge по умолчанию.

| Продукт | Что делает | Где живёт |
|---------|------------|-----------|
| **FlowNote** | Заметки, идеи, утилиты. Опциональное шифрование в браузере | `index.html` (GitHub Pages) |
| **FlowPhoto** | Приватный обмен фото (AES-GCM в браузере) | `flowphoto-server/` → Render |
| **FlowVault** | Личный сейф фото в FlowPhoto (пароль, без email) | `/vault` на FlowPhoto |

## Быстрый старт

**FlowNote (локально):** открой `index.html` в браузере или задеплой корень репозитория на GitHub Pages.

**FlowPhoto (локально):**

```bash
cd flowphoto-server
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Открой http://127.0.0.1:8000/

## Конфигурация ссылок

- `public-config.json` — URL FlowNote и FlowPhoto для GitHub Pages
- `flow-config.js` — подгружает конфиг и проставляет ссылки

## Деплой

- **FlowNote:** GitHub Pages (`index.html` в корне)
- **FlowPhoto:** `render.yaml` → **Starter + disk 1GB** + Docker

**Render Free** не сохраняет данные. Бесплатная страховка — [Cloudflare R2](flowphoto-server/README.md#starter-vs-free) (бэкап БД).

Подробности сервера: [flowphoto-server/README.md](flowphoto-server/README.md)

## Архив

Внутренние планы и скрипты разработки — в папке [`archive/`](archive/). На работу сайта не влияют.

## Юридические документы

- [privacy.html](privacy.html) — Политика конфиденциальности
- [terms.html](terms.html) — Условия использования

## Безопасность

См. [archive/AUDIT-REPORT.md](archive/AUDIT-REPORT.md) — аудит перед публичным запуском.