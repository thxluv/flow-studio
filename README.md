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

## Деплой и управление

**Шпаргалка:** [УПРАВЛЕНИЕ.md](УПРАВЛЕНИЕ.md) — ссылки, мониторинг, env, Storj.

- **Залить изменения:** двойной клик `deploy.bat`
- **FlowNote:** GitHub Pages (обновляется после push)
- **FlowPhoto:** Render Free + Docker, бэкап в [Storj 25 ГБ](archive/STORJ-FREE-RENDER.md) каждые 30 мин
- **Env для Render:** `archive/render-flowphoto.env` → импорт в Dashboard

Подробности сервера: [flowphoto-server/README.md](flowphoto-server/README.md)

## Статус и планы

**[СТАТУС-ПРОЕКТА.txt](СТАТУС-ПРОЕКТА.txt)** — суть проекта, что сделано, чекап, roadmap.

## Архив

Справочники (Storj, env-шаблон) — в [`archive/`](archive/).

## Юридические документы (ред. 2.2)

- [privacy.html](privacy.html) — Политика конфиденциальности
- [terms.html](terms.html) — Условия использования
- [law-enforcement.html](law-enforcement.html) — Для правоохранительных органов

## Безопасность

См. [archive/AUDIT-REPORT.md](archive/AUDIT-REPORT.md) — аудит перед публичным запуском.