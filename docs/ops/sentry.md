# Sentry (xato kuzatuvi) [P12-T1]

`config/settings/prod.py` — FAQAT `SENTRY_DSN` berilganda yoqiladi
(dev/test har doim o'chiq). Web (Django) + Celery worker/beat bitta init
bilan qamraladi (worker prod settings bilan ishga tushadi).

## Yoqish [R1-T1]

1. sentry.io da project (Django) yarating → **Client Keys (DSN)** nusxalang.
2. Serverda `.env`: `SENTRY_DSN=https://...@....ingest.sentry.io/...`
   (environment default `production` — alohida sozlash shart emas).
3. Restart (image o'zgarmaydi, faqat env):
   ```sh
   cd /opt/drama
   IMAGE_TAG=$(cat .deploy/current_tag) docker compose \
       -f docker-compose.yml -f docker-compose.prod.yml \
       up -d --no-build web celery-worker celery-beat
   ```
4. Smoke test (quyida) → event Issues'da ko'ringach, sinov-eventni o'chiring.

## Release tracking (avtomatik)

Release = **image tegi (SHA12)**, zanjiri: `deploy.yml` build-arg
`GIT_SHA=<tag>` → `Dockerfile` `ENV GIT_SHA` → `prod.py`
`release=SENTRY_RELEASE || GIT_SHA || None`. Ya'ni image o'z versiyasini
o'zi biladi — `.env`ni har deploy'da yangilash KERAK EMAS, har xato "qaysi
deploy'da paydo bo'ldi" bilan avtomatik bog'lanadi.

`SENTRY_RELEASE` env'i faqat qo'lda override uchun qoldi (odatda bo'sh).
Eslatma: lokal/CI buildda (build-arg'siz) release `None` — bu kutilgan.

## PII siyosati

- `send_default_pii=False` — email/username/IP YUBORILMAYDI, faqat `user.id`;
- sentry-sdk default EventScrubber sezgir kalitlarni (password, token,
  secret, authorization...) avtomatik o'chiradi;
- request body default yuborilmaydi.

## Smoke test (prod serverda, DSN o'rnatilgach)

    python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('drama.uz sentry smoke')"

1-2 daqiqada sentry.io Issues'da ko'rinishi kerak. Celery tomonini sinash:
biror task ichida ataylab xato (yoki mavjud retry-xato) — worker eventi
`celery` teg bilan tushadi.

## Performance

`SENTRY_TRACES_SAMPLE_RATE=0.1` (10%). Trafik oshsa kamaytiring (narx);
debug uchun vaqtincha 1.0 qilib qo'yish mumkin.
