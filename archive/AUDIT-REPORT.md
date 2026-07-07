# Flow Studio — отчёт аудита безопасности и публикации

**Дата:** 8 июля 2026  
**Версия FlowPhoto:** 3.3.0  
**Аудитор:** security + devops review (pre-public release)

---

## 1. Общая оценка безопасности

| Уровень | Количество | Комментарий |
|---------|------------|-------------|
| **High** | 6 | Блокеры или обязательные фиксы до публичного запуска |
| **Medium** | 12 | Исправить в ближайшие 1–2 недели |
| **Low** | 8 | Улучшения, hardening, документация |

**Итоговая оценка:** архитектура **в целом честная** для zero-knowledge обмена фото, но публичный запуск **сейчас преждевременен** без устранения High-рисков (секреты, oracle-эндпоинты, CSP, юридические документы, ephemeral storage на Free).

**Сильные стороны:**
- Шифрование фото в браузере (AES-GCM 256), ключ в `#` фрагменте — сервер не получает ключ
- FlowNote: DEK + wrap через PBKDF2 310k, отдельная recovery-фраза
- PBKDF2 600k для хешей паролей на сервере
- Rate limit на `/view/` и `/raw/`
- Security headers (nosniff, DENY frame, no-referrer)
- `.gitignore` закрывает `.env`, `flowphoto.db`, uploads

**Слабые стороны:**
- Нет CSP / SRI на CDN-зависимостях
- FlowVault **не полностью** zero-knowledge (хеш пароля на сервере + oracle)
- Free Render = потеря данных при рестарте
- Нет Privacy Policy / Terms
- Abuse-векторы на upload и vault API без rate limit

---

## 2. Критические проблемы (High)

### H1. Дефолтный `FLOWPHOTO_VAULT_SECRET` в коде
**Файл:** `flowphoto-server/app/security.py:17`  
```python
os.environ.get("FLOWPHOTO_VAULT_SECRET", "flowphoto-dev-change-me-in-production")
```
Если на Render не задан секрет — токены Vault и upload_claim подписываются предсказуемым значением из публичного репозитория. **Любой может подделать claim.**

**Действие:** обязательный секрет ≥32 байт в env; при старте падать, если secret = default.

---

### H2. Oracle «пароль уже существует» (`/api/vault/check`)
**Файл:** `flowphoto-server/app/main.py`, `vault.py:password_exists`  
Эндпоинт перебирает **все** хеши vault в БД и отвечает `exists: true/false`. Это:
- утечка факта существования пароля;
- помощь офлайн-атаке (узкий словарь + подтверждение);
- DoS при росте базы (O(n) на запрос).

**Действие:** убрать публичный check или заменить на constant-time «всегда одинаковый ответ» + rate limit.

---

### H3. FlowPhoto на Render Free — эфемерный диск
**Файл:** `render.yaml` — `plan: free`, диск закомментирован  
При рестарте/деплое **все фото и vault исчезают**. Для публичного сервиса это не баг, а **потеря данных пользователей**.

**Действие:** Starter + persistent disk **или** обязательный R2-бэкап + предупреждение в UI.

---

### H4. Нет Content-Security-Policy (FlowNote + FlowPhoto)
**Файлы:** `index.html`, `flowphoto-server/templates/base.html`  
Загружаются скрипты с CDN без SRI:
- `cdn.tailwindcss.com` (компилирует CSS/JS на лету — **полный XSS при компрометации CDN**)
- jspdf, qrcode, font-awesome

**Действие:** CSP `default-src 'self'`, whitelist CDN, `script-src` с nonce или self-hosted bundles + SRI.

---

### H5. Stored XSS в FlowNote (innerHTML без экранирования)
**Файл:** `index.html` — `renderSavedNotes()`, `renderIdeas()` и др.  
`note.content` вставляется в `innerHTML` без escape. Вредоносный HTML в заметке выполнится при просмотре списка.

**Действие:** `textContent` / DOMPurify / шаблоны с escape для всего user-generated контента.

---

### H6. Юридическая неготовность (РФ)
- Нет **Privacy Policy** и **Terms of Service**
- FlowPhoto на **Render (США)** — трансграничная передача метаданных и ciphertext
- 152-ФЗ: нужны цели обработки, согласие/уведомление, политика хранения
- Нет контактов оператора, нет возрастных/контентных ограничений (用户 могут грузить любые image/*)

**Действие:** минимальный комплект документов + disclaimer «сервис без гарантий / beta».

---

## 3. Средние проблемы (Medium)

### M1. FlowVault — не полный zero-knowledge
| Что | Где | Риск |
|-----|-----|------|
| Хеш пароля vault | SQLite | Офлайн brute-force при утечке БД |
| Метаданные (имя файла, id, просмотры) | SQLite | Корреляция, traffic analysis |
| Ciphertext фото | SQLite | Без ключа бесполезно — **ОК** |
| Ключи `#` | localStorage | Только у клиента — **ОК** |
| upload_claim | localStorage | Потеря устройства = потеря прав без `.flowvault` бэкапа |

Минимальный пароль vault: **4 символа** — слабо.

---

### M2. Rate limiting неполный
- Есть: `/view/*`, `/raw/*` (60 req/min/IP, in-memory)
- **Нет:** `/upload`, `/api/vault/*`, `/info/*`
- In-memory сбрасывается при рестарте; не работает при горизонтальном масштабировании

---

### M3. `/health` раскрывает инфраструктуру
Возвращает `data_dir`, `storage_bytes`, `backup_configured`, `version`. Полезно для атакующего.

---

### M4. CORS: localhost в DEFAULT_ORIGINS
`main.py` всегда разрешает `127.0.0.1:8000` — на проде лишнее (низкий риск без credentials).

---

### M5. Recovery phrase в FlowNote — `Math.random()`
`generateRecoveryPhrase()` использует `Math.random()`, не `crypto.getRandomValues`. 6 слов из фиксированного словаря — энтропия ниже BIP39.

---

### M6. localStorage — единая точка отказа
FlowNote: весь vault + security config в localStorage (XSS = полная компрометация).  
FlowPhoto: ключи vault в localStorage.  
Нет защиты от расширений браузера / malware на устройстве.

---

### M7. Бэкап SQLite в R2/S3 — ciphertext остаётся ciphertext, но...
При утечке бэкапа БД: метаданные + хеши vault + зашифрованные фото. Не ключи фото, но **хеши паролей vault**.

---

### M8. Upload abuse / storage exhaustion
Лимит 500 МБ и 25 МБ/файл есть, но **нет CAPTCHA / auth / upload rate limit**. Злоумышленник может забить диск.

---

### M9. `password_exists` — timing side-channel
`verify_secret` на всех vault подряд; разное время ответа при совпадении.

---

### M10. Нет HSTS / CSP на уровне Render
Только middleware FastAPI; GitHub Pages — отдельная поверхность.

---

### M11. `flowphoto.html` — hardcoded production URL
Meta refresh на `flowphoto.onrender.com`; локальная разработка через fetch `/health` — ок, но нет явного предупреждения о mixed content.

---

### M12. Отсутствие Subresource Integrity
Все CDN-скрипты без `integrity=` — supply chain risk.

---

## 4. Низкие проблемы (Low)

- `index.html` ~4700 строк монолит — сложность аудита и регрессий
- Дублирование PBKDF2 итераций (310k клиент / 600k сервер) — не баг, но документировать
- `view.html` innerHTML для meta — данные с сервера (контролируемые), низкий XSS
- `vault.html` использует `escapeHtml` для имён — **хорошо**
- Нет мониторинга/алертов на 507 storage full
- Нет версионирования API
- `terminals/` в рабочей папке — в `.gitignore`, ок
- `flowphoto.db` локально — в `.gitignore`, ок

---

## 5. Детали по направлениям аудита

### A. FlowNote Studio (`index.html`)

| Параметр | Оценка |
|----------|--------|
| PBKDF2 310k + SHA-256 | ✅ Соответствует современным рекомендациям (OWASP) |
| AES-GCM 256 + 12-byte IV | ✅ Корректно |
| DEK + dual wrap (password + recovery) | ✅ Хорошая модель |
| Итерации при export backup | ✅ PBKDF2 310k в export flow |
| Recovery entropy | ⚠️ Math.random + 6 слов |
| Хранение | localStorage plaintext до включения security; после — encrypted blob |
| IndexedDB для фото | ❌ Не реализовано (только в планах в archive) |
| CSP | ❌ |
| XSS | ❌ innerHTML в списках заметок/идей |
| CDN | ⚠️ tailwind CDN особенно рискован |

### B. FlowPhoto + FlowVault

| Параметр | Оценка |
|----------|--------|
| E2E фото | ✅ Ключ не на сервере |
| EXIF strip | ✅ Canvas re-encode |
| short_id 58^12 | ✅ ~70 бит энтропии |
| Link password (2nd factor) | ✅ Хеш на сервере |
| FlowVault backup `.flowvault` | ✅ Клиентское шифрование PBKDF2+AES-GCM |
| Vault ZK claim | ⚠️ Частично — пароль и метаданные на сервере |
| `flow-config.js` | ✅ Только публичные URL, fetch public-config.json |
| `public-config.json` | ✅ Нет секретов |

### C. Архитектура и деплой

```
GitHub Pages (FlowNote)  ──►  static, no backend
        │
        └── flow-config.js ──► public-config.json
                                    │
Render (FlowPhoto Docker)  ◄────────┘
        │
        ├── SQLite /data (ephemeral on Free)
        └── optional R2 backup (encrypted at rest as file, not E2E)
```

**Локаль vs прод:** `flowphoto.html` автоопределяет localhost:8000 — удобно для dev, не влияет на prod security.

### D. Юридические риски (РФ) — кратко

1. **152-ФЗ:** обработка персональных данных (IP, метаданные файлов, потенциально EXIF до strip) — нужна политика.
2. **Трансграничная передача:** Render US — указать в политике.
3. **Ответственность за контент:** пользователи могут хранить незаконный контент — нужен ToS с запретом и процедурой удаления.
4. **Нет реестра оператора** — для некоммерческого pet-project часто достаточно политики на сайте, но **юрист обязателен** для уверенности.

---

## 6. Что перемещено в `archive/`

| Файл | Причина |
|------|---------|
| `ДЕПЛОЙ.txt` | Внутренняя инструкция |
| `ПУБЛИЧНЫЙ-ЗАПУСК.txt` | Чеклист запуска |
| `обзор-проекта.txt` | Обзор для разработки |
| `план.txt` | План фич |
| `сложные-задачи-позже.txt` | Backlog |
| `статус-проекта.txt` | Статус |
| `deploy.bat` | Локальный деплой GH Pages |
| `deploy.ps1` | Локальный деплой GH Pages |
| `start-flowphoto.bat` | Локальный запуск |
| `flowphoto-server/render.yaml` | Дубликат корневого `render.yaml` |

---

## 7. Структура репозитория после уборки

```
flow-studio/
├── index.html              # FlowNote (GitHub Pages)
├── flowphoto.html          # Редирект на FlowPhoto
├── flow-config.js
├── public-config.json
├── render.yaml             # Blueprint Render
├── README.md
├── .gitignore
├── flowphoto-server/       # Backend FlowPhoto + FlowVault
│   ├── app/
│   ├── templates/
│   ├── static/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md
└── archive/                # Не для продакшена
    ├── AUDIT-REPORT.md
    ├── README.md
    └── … (планы, скрипты)
```

**Оставлено намеренно:** весь код `flowphoto-server/` — это исходники, не артефакты.

---

## 8. Что сделать дальше (приоритетный backlog)

### P0 — до публичного анонса
1. [ ] Задать `FLOWPHOTO_VAULT_SECRET` на Render; fail-fast если default
2. [ ] Убрать или защитить `/api/vault/check`
3. [ ] Persistent storage (Starter disk) или явный disclaimer «данные могут исчезнуть»
4. [ ] CSP + убрать tailwind CDN (собрать статический CSS)
5. [ ] Escape XSS в FlowNote списках
6. [ ] Privacy Policy + Terms (хотя бы `privacy.html` / `terms.html` на Pages)

### P1 — первая неделя после запуска
7. [ ] Rate limit на `/upload` и `/api/vault/*`
8. [ ] Минимум 8–12 символов для vault password
9. [ ] `crypto.getRandomValues` для recovery phrase
10. [ ] SRI на оставшихся CDN или self-host
11. [ ] Сократить `/health` для публики (отдельный `/health/public`)

### P2 — улучшения
12. [ ] CAPTCHA или proof-of-work на upload
13. [ ] Redis rate limit для multi-instance
14. [ ] Аудит-лог без PII
15. [ ] README для пользователей: «что видит сервер / что нет»
16. [ ] Юридическая консультация по 152-ФЗ

---

*Отчёт подготовлен автоматически по состоянию репозитория на момент аудита. Не заменяет pentest и юридическую экспертизу.*