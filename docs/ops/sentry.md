# Sentry (xato kuzatuvi) [P12-T1]

`config/settings/prod.py` — FAQAT `SENTRY_DSN` berilganda yoqiladi
(dev/test har doim o'chiq). Web (Django) + Celery worker/beat bitta init
bilan qamraladi (worker prod settings bilan ishga tushadi).

## Yoqish

1. sentry.io da project (Django) yarating → **Client Keys (DSN)** nusxalang.
2. `.env`: `SENTRY_DSN=https://...@....ingest.sentry.io/...`
3. Restart (web + celery-worker + celery-beat).

## Release tracking

Deploy skriptida (P13-T2 da avtomatlashadi):

    SENTRY_RELEASE=$(git rev-parse --short HEAD)

Shunda har xato "qaysi deploy'da paydo bo'ldi" bilan bog'lanadi.

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
