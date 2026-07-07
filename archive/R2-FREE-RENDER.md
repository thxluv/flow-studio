# FlowPhoto: Render Free + Cloudflare R2 (устарело — см. STORJ-FREE-RENDER.md)

> **Рекомендуем Storj:** 25 ГБ free, только email → [`STORJ-FREE-RENDER.md`](STORJ-FREE-RENDER.md)

# FlowPhoto: Render Free + Cloudflare R2 (пошагово)

Цель: бесплатный хостинг на Render, фото не пропадают навсегда — база копируется в R2, после рестарта подтягивается обратно.

**Важно:** ключи расшифровки фото (`#...` в ссылке) по-прежнему только у пользователя в браузере. R2 хранит зашифрованные файлы и метаданные в SQLite.

---

## Часть 1. Cloudflare R2 (хранилище бэкапов)

### 1.1 Регистрация / вход

1. Открой https://dash.cloudflare.com/
2. Войди или зарегистрируйся (бесплатно).

### 1.2 Включить R2

1. В левом меню: **R2 object storage** (или поиск «R2»).
2. Если просят привязать карту — на free tier списания обычно $0 в пределах лимита; можно привязать для активации.

### 1.3 Создать bucket (корзину)

1. Кнопка **Create bucket**.
2. **Bucket name:** `flowphoto-backup` (любое уникальное имя латиницей).
3. Location: **Automatic** → **Create bucket**.

Запомни имя — это `FLOWPHOTO_BACKUP_BUCKET`.

### 1.4 Узнать Account ID

1. Справа в R2 или в URL дашборда виден **Account ID** (32 символа hex).
2. Или: **R2** → в правой колонке **Account ID**.

Endpoint будет:
```
https://<ACCOUNT_ID>.r2.cloudflarestorage.com
```
Подставь свой ID вместо `<ACCOUNT_ID>`.

### 1.5 API-токен для Render

1. В R2: **Manage R2 API Tokens** (справа сверху).
2. **Create API token**.
3. **Token name:** `flowphoto-render`
4. Permissions: **Object Read & Write**
5. Specify bucket: только твой bucket `flowphoto-backup`
6. **Create API Token**

Сразу скопируй (показывают один раз):

| Что | Куда в Render |
|-----|----------------|
| Access Key ID | `FLOWPHOTO_BACKUP_ACCESS_KEY` |
| Secret Access Key | `FLOWPHOTO_BACKUP_SECRET_KEY` |

---

## Часть 2. Render (сервер FlowPhoto)

### 2.1 Открыть сервис

1. https://dashboard.render.com/
2. Сервис **flowphoto** (или как назвал).

### 2.2 Тариф Free

1. **Settings** → **Instance Type**
2. Выбери **Free** (если был Starter — переключи на Free).
3. **Disk:** если добавлял диск для Starter — можно **удалить** (на Free он платный). Данные на диске всё равно эфемерны без paid disk.

### 2.3 Environment Variables

**Environment** → **Add Environment Variable** (или Edit).

Уже должны быть (не трогай):

| Key | Value |
|-----|-------|
| `FLOWNOTE_PUBLIC_URL` | `https://thxluv.github.io/flow-studio/index.html` |
| `FLOWPHOTO_DATA_DIR` | `/data` |
| `FLOWPHOTO_MAX_STORAGE_BYTES` | `524288000` |
| `FLOWPHOTO_RATE_MAX` | `60` |
| `FLOWPHOTO_RATE_WINDOW` | `60` |
| `FLOWPHOTO_VAULT_SECRET` | Secret (твой ключ, ≥32 символов) |
| `PORT` | `8000` |

**Добавь для R2:**

| Key | Value | Тип |
|-----|-------|-----|
| `FLOWPHOTO_BACKUP_BUCKET` | `flowphoto-backup` | обычный |
| `FLOWPHOTO_BACKUP_ACCESS_KEY` | из Cloudflare | **Secret** |
| `FLOWPHOTO_BACKUP_SECRET_KEY` | из Cloudflare | **Secret** |
| `FLOWPHOTO_BACKUP_ENDPOINT` | `https://ТВОЙ_ACCOUNT_ID.r2.cloudflarestorage.com` | обычный |
| `FLOWPHOTO_BACKUP_PREFIX` | `flowphoto` | обычный |
| `FLOWPHOTO_BACKUP_INTERVAL` | `3600` | обычный (бэкап каждый час) |

**Save Changes.**

### 2.4 Деплой

1. **Manual Deploy** → **Deploy latest commit**
2. Подожди 5–10 минут, статус **Live**.

### 2.5 Проверка

Открой в браузере:
```
https://flowphoto.onrender.com/health
```

Должно быть:
```json
"backup_configured": true
```

Если `false` — не хватает одной из переменных R2.

---

## Часть 3. Как это работает

```
Загрузка фото → SQLite на Render (временно)
       ↓ каждый час (или при старте)
Копия flowphoto.db → Cloudflare R2
       ↓ рестарт / sleep Render Free
Пустая БД → скачать последний .db из R2 → снова работает
```

**Ограничения Free:**

- Между бэкапами до 1 часа потери (если упал сразу после загрузки).
- Первый бэкап — после первого часа с данными или при рестарте после того как уже был бэкап.
- Render Free «засыпает» — первый запрос после сна ~30–60 сек.

---

## Часть 4. Проверка «как пользователь»

1. Загрузи тестовое фото на https://flowphoto.onrender.com/
2. Подожди 1 час **или** сделай Manual Deploy (при старте идёт бэкап если БД не пустая).
3. В Cloudflare R2 → bucket → **Objects** — должен появиться файл `flowphoto/flowphoto_YYYYMMDD_HHMMSS.db`
4. **Manual Deploy** ещё раз — после старта фото должны открываться по старым ссылкам (если ключ `#` сохранён у тебя в браузере).

---

## Часть 5. FlowVault

Пароль vault и ключи `#` — в браузере / файле `.flowvault`. R2 бэкапит **серверную** БД (хеши vault, ciphertext). Без локального бэкапа `.flowvault` после смены устройства ключи не вернуть.

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `backup_configured: false` | Проверь все 4–5 переменных R2 |
| Бэкап не появляется в R2 | Подожди 1ч или redeploy; в логах Render ищи `Backup uploaded` |
| После рестарта пусто | В R2 нет ни одного `.db` — сначала нужен хотя бы один успешный бэкап |
| 502 после сна | Подожди минуту, Free просыпается |

Логи Render: сервис → **Logs** → фильтр `backup` / `Restore`.