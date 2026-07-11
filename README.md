# 🎬 Drama.uz

Koreys va Osiyo dramalarini (kino-serial) ko'rish uchun **production darajasidagi Django SaaS platforma**. Crowdfunding (tarjima uchun mablag' yig'ish), VIP obuna, **Coin** (ichki valyuta) tizimi, aktyor profillari va **Bunny Stream** orqali adaptiv video uzatish.

> ⚙️ **Holat:** loyiha kuchli fundament ustiga faol qayta qurilmoqda (`drama_tasks.json` rejasi bo'yicha). Quyida joriy progress keltirilgan.

---

## ✨ Asosiy imkoniyatlar

- 🎞 **Katalog** — kinolar, **fasllar (Season)**, qismlar (Episode), janrlar, teglar, kategoriyalar, aktyorlar
- 🔒 **Kirish nazorati** — 1–10-qism bepul, 11-qismdan boshlab **VIP** yoki **crowdfunding** orqali
- 💰 **Coin tizimi** — ichki valyuta: UZS chek yoki kripto (USDT) orqali to'ldirish (admin tasdig'i bilan)
- 🤝 **Crowdfunding** — tarjima loyihalariga hissa qo'shish (`funding` app)
- 🎁 **Aktyorga sovg'a** — Coin evaziga aktyorlarga sovg'a yuborish
- ▶️ **Davom ettirish** — `WatchProgress` orqali qaysi sekundda to'xtaganini saqlash
- 🖼 **Avtomatik rasm optimizatsiyasi** — WEBP siqish fon (Celery)da, request bloklanmasdan
- 🌐 **i18n** — o'zbek / ingliz (`django-modeltranslation`)
- 🛠 **Zamonaviy admin** — `django-unfold` asosida

---

## 🛠 Texnologiyalar

| Qatlam | Texnologiya |
|--------|-------------|
| Til / Framework | Python 3.12, **Django 6.0** |
| Ma'lumotlar bazasi | PostgreSQL 16 |
| Kesh / Broker / Sessiya | Redis 7 (`django-redis`) |
| Fon vazifalar | Celery 5 + Celery Beat |
| Video | Bunny Stream (HLS adaptiv) |
| Media (rasm) | Google Cloud Storage (`cdn.drama.uz`, WEBP) |
| Auth | `django-allauth` (+ JWT: `simplejwt` — API uchun) |
| Frontend | Django Templates (SSR) + HTMX + Tailwind |
| Admin | `django-unfold` |
| Deploy | Docker Compose (web, db, redis, celery, beat, nginx) |
| Kod sifati | ruff (lint+format), mypy, pre-commit, pytest |

---

## 📁 Loyiha tuzilishi

```
drama-vps/
├── config/
│   ├── settings/          # base / dev / prod / test (DJANGO_SETTINGS_MODULE orqali)
│   ├── celery.py          # Celery app
│   ├── logging.py         # tuzilmali logging (dev konsol / prod JSON)
│   └── urls.py, wsgi.py, asgi.py
├── core/                  # umumiy: health-check, rasm optimizatsiyasi (mixin)
├── drama/                 # katalog: Movie, Season, Episode, Actor, Genre, Tag, Review...
├── users/                 # Profile, Coin, UserMovieList, WatchProgress, top-up
├── funding/               # crowdfunding (FundingProject / Contributor)
├── templates/             # SSR shablonlar (HTMX + Tailwind)
├── requirements/          # base / dev / prod + lock.txt
├── docker/                # entrypoint.sh
├── nginx/                 # default.conf (reverse proxy + gzip + cache)
├── Dockerfile             # multi-stage (builder → runtime, non-root)
├── docker-compose.yml         # to'liq stack (prod-leaning)
├── docker-compose.dev.yml     # dev override (hot-reload)
└── drama_tasks.json       # qayta qurish rejasi (15 faza, 65 task)
```

---

## 🚀 Tez boshlash (Docker)

Talab: **Docker Desktop** (Compose v2). Boshqa hech narsa kerak emas — Postgres/Redis konteynerlarda keladi.

```bash
# 1. Sirlar faylini tayyorlang
cp .env.example .env
#   .env ichida kamida SECRET_KEY va DB_PASSWORD ni to'ldiring.
#   SECRET_KEY yaratish (MUHIM: $ belgisiz!):
#   python -c "import secrets; print('django-insecure-' + secrets.token_urlsafe(50))"

# 2. Dev stack'ni ko'taring (hot-reload, runserver, sqlite EMAS — postgres)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# 3. Boshqa terminalda — superuser yarating
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

Endi:
- 🌐 Sayt: <http://localhost:8000>
- 🔐 Admin: <http://localhost:8000/admin/>
- ❤️ Sog'lik: <http://localhost:8000/healthz> · <http://localhost:8000/readyz>

**Dev stack tarkibi:** `web` (runserver), `db` (postgres16), `redis`, `celery-worker`, `celery-beat`. `nginx` dev'da o'chiq (runserver statikani o'zi beradi). Kod o'zgarishi darhol qayta yuklanadi (`.:/app` mount).

To'xtatish (ma'lumotlar saqlanadi):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

> **Prod stack:** `docker compose up -d` — `web` gunicorn + `nginx` bilan. Prod `config.settings.prod` ni yuklaydi (GCS kaliti va SMTP talab qilinadi).

---

## ⚙️ Muhit o'zgaruvchilari (`.env`)

`.env.example` dan nusxa oling. Asosiy o'zgaruvchilar:

| O'zgaruvchi | Tavsif |
|-------------|--------|
| `SECRET_KEY` | Django maxfiy kaliti — **`$` belgisiz** (Docker `.env` interpolatsiyasini buzadi) |
| `DEBUG` | dev'da avtomatik `True` (dev.py), prod'da `False` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL (Docker'da `DB_HOST=db` avtomatik) |
| `REDIS_URL` | kesh/sessiya (Docker'da `redis://redis:6379/1` avtomatik) |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` yoki `.prod` |
| `BUNNY_STREAM_*` | video kutubxonasi (Library ID, CDN host, API key) |
| `TELEGRAM_BOT_TOKEN` / `..._ADMIN_CHAT_ID` | admin xabarnomalari |
| `GS_CREDENTIALS_FILE` | GCS xizmat-akkaunt kaliti yo'li (faqat prod) |
| `EMAIL_*` | SMTP (faqat prod; dev'da konsolga chiqadi) |

> ⚠️ `.env`, `*.key.json` va DB dump'lar **hech qachon** git'ga commit qilinmaydi (`.gitignore`).

---

## 🧪 Testlar va kod sifati

Testlar **sqlite (xotira)** da ishlaydi — tashqi DB kerak emas, host'da ham tez:

```bash
# venv'ni faollashtiring (lokal)
python -m pytest                      # barcha testlar
python -m pytest drama/tests.py -v    # bitta modul
```

Kod sifati (pre-commit — ruff, mypy, django-upgrade, fayl-gigiena):

```bash
pre-commit install            # bir marta (git hook)
pre-commit run --all-files    # qo'lda to'liq tekshirish
```

> ⚠️ Lokal pre-commit hook'lari venv vositalarini ishlatadi. Commit qilishdan oldin venv'ni PATH'ga qo'shing (Windows):
> ```powershell
> $env:PATH = "C:\projects\drama-vps\env\Scripts;$env:PATH"
> ```

---

## 🗂 Foydali buyruqlar

Docker ichida (`docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web ...`):

```bash
python manage.py migrate                 # migratsiyalar
python manage.py makemigrations          # yangi migratsiya
python manage.py createsuperuser         # admin
python manage.py optimize_images --sync  # mavjud rasmlarni WEBP'ga siqish (backfill)
python manage.py optimize_images --dry-run   # faqat sanash
```

Celery (dev stack'da avtomatik ishlaydi; qo'lda):
```bash
celery -A config worker -l info
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## 🏗 Arxitektura eslatmalari

- **Settings split** — `config/settings/{base,dev,prod,test}.py`. `manage.py` → dev, `wsgi/asgi` → prod default. Sirlar `python-decouple` orqali `.env` dan.
- **Rasm optimizatsiyasi (P1-T1)** — `core.images.ImageOptimizationMixin` rasm maydonlarini `save()`'da emas, `transaction.on_commit` orqali **Celery task'ga** beradi → admin/request bloklanmaydi, WEBP siqish fonda. Mixin `object` merosxo'ri, shuning uchun migratsiya talab qilmaydi.
- **Season strukturasi (P1-T2)** — `Movie → Season → Episode`. Backward-compatible: `Episode.movie` saqlanadi va `Episode.season` `null=True`; data migration mavjud episodelarni "Season 1"ga bog'laydi.
- **WatchProgress (P1-T3)** — `unique(user, episode)` + indeks `(user, -updated_at)`. Pleyer har 10–15s `episode/<id>/progress/` ga POST yuboradi; 90%+ ko'rilsa avto-`completed`.
- **Health-check** — `/healthz` (yengil) va `/readyz` (DB + Redis + migratsiya). Docker healthcheck shularga tayanadi.

---

## 📈 Holat / Roadmap

Reja ikki tracker'da: `drama_tasks.json` (v1: 15 faza / 65 task — **58 done**) va `drama-vps-v2_tasks.json` (v2: 8 faza / 32 task — navbatda). Bosqichlar va ustuvorlik: **`roadmap.md`** (2026-07-10 audit: arxitektura **82/100** · UX **76/100**).

- ✅ **To'liq yopilgan fazalar:** P1 data-model (Coin-ledger · Season · WatchProgress · publish-workflow) · P2 DRF API (JWT · signed playback) · P3 Celery (Bunny upload · webhook · bildirishnoma · beat) · P4 video xavfsizligi (signed URL) · P5 frontend (Alpine · pleyer · SEO · PWA) · P6 auth (email-tasdiqlash · Google/Telegram) · P8 qidiruv (FTS · tavsiyalar) · P11 testlar (321 birlik+API+E2E · coverage-gate) · P13 CI/CD (zero-downtime deploy · backup · staging)
- ⏳ **Qisman:** P0 8/9 — *qolgan: **P0-T2 sirlar rotatsiyasi (LAUNCH-BLOCKER)** → `docs/ops/secret-rotation.md`* · P7 3/4 (Payme/obuna/funding-hardening ✅; kripto-avto P7-T3 ochiq) · P9 2/3 (P9-T3: pgbouncer/cursor) · P10 4/5 (P10-T5: GDPR) · P12 1/2 (P12-T2: uptime/metrika) · P14 2/4 (P14-T2/T4: scheduling/analitika)

---

## ⚠️ Production deploy eslatmasi

`0016_sync_model_drift` migratsiyasi `bunny_video_id` / `bunny_trailer_id` maydonlarini qo'shadi. Agar **mavjud production DB'da bu ustunlar allaqachon bor bo'lsa** (qo'lda qo'shilgan), migratsiyani soxta (fake) qo'llang:

```bash
python manage.py migrate --fake drama 0016
python manage.py migrate   # qolganini odatdagidek
```

---

*Drama.uz — Django 6 SaaS. Ichki loyiha.*
