# FlowPhoto: Render Free + Storj (25 ГБ бесплатно)

**Зачем:** Render Free стирает данные при рестарте. Копия `flowphoto.db` уходит в Storj каждые **30 минут**; после рестарта сервер подтягивает последний бэкап.

**Лимит Storj (email):** ~25 ГБ — нам хватает (до 500 МБ на сервере, в облаке храним **12** последних копий).

---

## ЧАСТЬ 1. Storj (5–10 минут)

### 1. Регистрация

1. Открой https://www.storj.io/
2. **Get Started** / **Sign Up** — только **email** (без карты на free tier).
3. Подтверди почту, войди в https://login.storj.io/ (или Project Dashboard).

### 2. Проект

1. Если спросят — создай **Project** (имя любое, например `flowphoto`).
2. Попадёшь в **Storj DCS Dashboard**.

### 3. Bucket (корзина)

1. Слева **Buckets** → **Create Bucket**.
2. **Bucket name:** `flowphoto-backup` (только строчные латинские буквы, цифры, дефис).
3. **Create**.

Это значение → `FLOWPHOTO_BACKUP_BUCKET` в Render.

### 4. S3 Credentials (ключи для Render)

1. Слева **Access** → **S3 Credentials** (или **Create S3 Credentials**).
2. **Name:** `flowphoto-render`
3. **Permissions:** Read & Write (или Full Access на этот bucket).
4. **Buckets:** выбери только `flowphoto-backup`.
5. **Create**.

Скопируй сразу (показывают один раз):

| Storj показывает | Переменная в Render |
|------------------|---------------------|
| Access Key | `FLOWPHOTO_BACKUP_ACCESS_KEY` |
| Secret Key | `FLOWPHOTO_BACKUP_SECRET_KEY` |
| Endpoint / Gateway | `FLOWPHOTO_BACKUP_ENDPOINT` |

**Endpoint** для hosted gateway Storj обычно:
```
https://gateway.storjshare.io
```

(Если в консоли другой URL — используй тот, что дали.)

---

## ЧАСТЬ 2. Render

### 1. Открыть сервис

https://dashboard.render.com/ → сервис **flowphoto**.

### 2. Тариф

**Settings** → **Instance Type** → **Free**.

### 3. Environment — удалить старые R2 (если были)

Удали или замени переменные с Cloudflare endpoint на Storj.

### 4. Добавить / обновить переменные

| Key | Value | Тип |
|-----|-------|-----|
| `FLOWPHOTO_BACKUP_BUCKET` | `flowphoto-backup` | обычный |
| `FLOWPHOTO_BACKUP_ACCESS_KEY` | из Storj | **Secret** |
| `FLOWPHOTO_BACKUP_SECRET_KEY` | из Storj | **Secret** |
| `FLOWPHOTO_BACKUP_ENDPOINT` | `https://gateway.storjshare.io` | обычный |
| `FLOWPHOTO_BACKUP_PREFIX` | `flowphoto` | обычный |
| `FLOWPHOTO_BACKUP_INTERVAL` | `1800` | обычный (30 мин) |
| `FLOWPHOTO_BACKUP_KEEP` | `12` | обычный |

Остальное **не трогай:** `FLOWPHOTO_VAULT_SECRET`, `FLOWPHOTO_DATA_DIR`, `PORT`, и т.д.

**Save Changes** → **Manual Deploy** → дождись **Live**.

### 5. Проверка

```
https://flowphoto.onrender.com/health
```

Нужно:
```json
"backup_configured": true
```

### 6. Проверка файлов в Storj

1. Storj Dashboard → **Buckets** → `flowphoto-backup`.
2. Загрузи тестовое фото на FlowPhoto.
3. Подожди 30 мин **или** сделай **Manual Deploy** (бэкап при старте, если БД не пустая).
4. В bucket должны появиться: `flowphoto/flowphoto_YYYYMMDD_HHMMSS.db`

---

## Как это работает

```
Фото → SQLite на Render (временно)
         ↓ каждые 30 мин
    копия .db → Storj (25 ГБ free)
         ↓ рестарт Render
    пустая БД → скачать последний .db → снова работает
```

Старые копии **удаляются автоматически** — остаётся 12 последних (~6 часов истории).

---

## Частота бэкапа

| INTERVAL | Частота |
|----------|---------|
| `1800` | 30 минут (по умолчанию) |
| `900` | 15 минут |
| `600` | 10 минут |

На Storj free лимиты операций щедрые; узкое место — размер БД, не API.

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `backup_configured: false` | Нет bucket / keys / endpoint |
| Ошибка в логах `403` / `AccessDenied` | S3 credential без Write на bucket |
| Ошибка `endpoint` | Проверь `https://gateway.storjshare.io` без слэша в конце |
| Пусто в bucket | Сначала загрузи фото, потом redeploy или подожди 30 мин |
| После рестарта пусто | В bucket ещё нет ни одного `.db` |

Render → **Logs** → ищи `Backup uploaded` или `Restore`.

---

## R2 vs Storj

| | Cloudflare R2 | Storj |
|--|---------------|-------|
| Free | 10 ГБ | **25 ГБ** |
| Регистрация | часто карта | **email** |
| Endpoint | `https://<id>.r2.cloudflarestorage.com` | `https://gateway.storjshare.io` |

Код один и тот же — меняются только env-переменные.