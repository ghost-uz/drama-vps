"""Prod muhiti — DEBUG=False, qat'iy xavfsizlik, GCS storage, SMTP email."""

from google.oauth2 import service_account

from config.logging import build_logging

from .base import *  # noqa: F403

DEBUG = False

# Majburiy — .env da bo'lmasa ataylab crash bo'ladi (xavfsizlik)
SECRET_KEY = config("SECRET_KEY")  # noqa: F405

ALLOWED_HOSTS = [
    "drama.uz",
    "www.drama.uz",
    "207.154.194.231",
]

# -- SSL / HTTPS (Cloudflare orqali) --
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 yil
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# SECURE_BROWSER_XSS_FILTER Django 4.0 da olib tashlangan (o'lik sozlama edi) [P10-T1]
SECURE_CONTENT_TYPE_NOSNIFF = True

# Clickjacking [P10-T1]: eski brauzerlar uchun fallback. Zamonaviy brauzerlar
# CSP frame-ancestors'ni ustun ko'radi — Telegram Web allowlist o'sha yerda
# (config/middleware.py); Telegram mobil/desktop nativ WebView (iframe emas).
X_FRAME_OPTIONS = "SAMEORIGIN"

# Admin 2FA prod'da DEFAULT YOQIQ [P10-T4] — birinchi kirishdan oldin serverda
# `manage.py bootstrap_totp <username>` bajarilishi SHART (aks holda qulf).
ADMIN_REQUIRE_2FA = config("ADMIN_REQUIRE_2FA", default=True, cast=bool)

# -- Cookie (Telegram WebView cross-site uchun) --
CSRF_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_DOMAIN = ".drama.uz"

# -- CORS / CSRF --
CORS_ALLOWED_ORIGINS = [
    "https://drama.uz",
    "https://www.drama.uz",
    "https://web.telegram.org",
]
CSRF_TRUSTED_ORIGINS = [
    "https://drama.uz",
    "https://www.drama.uz",
    "https://web.telegram.org",
]

# -- Email (SMTP) --
EMAIL_BACKEND = config(  # noqa: F405
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")  # noqa: F405
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)  # noqa: F405
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)  # noqa: F405
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")  # noqa: F405
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")  # noqa: F405
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="admin@drama.uz")  # noqa: F405

# -- Google Cloud Storage (CDN) --
# NOTE: P0-T2 da kalit repodan olib tashlanadi va rotatsiya qilinadi.
GS_CREDENTIALS_FILE = config(  # noqa: F405
    "GS_CREDENTIALS_FILE",
    default=str(BASE_DIR / "drama-key-v2.json"),  # noqa: F405
)
GS_CREDENTIALS = service_account.Credentials.from_service_account_file(GS_CREDENTIALS_FILE)

# Static/media obyektlarga cache header — collectstatic/yuklashda GCS'ga yoziladi,
# cdn.drama.uz shu bilan xizmat qiladi (1 kun; fayl nomlari hash'lanmagani uchun
# "immutable" EMAS) [P5-T1]
GS_OBJECT_PARAMETERS = {"cache_control": "public, max-age=86400"}

STATIC_URL = f"https://{GS_CUSTOM_DOMAIN}/static/"  # noqa: F405
MEDIA_URL = f"https://{GS_CUSTOM_DOMAIN}/media/"  # noqa: F405

STORAGES = {
    "default": {"BACKEND": "config.custom_storage.CustomMediaStorage"},
    "staticfiles": {"BACKEND": "config.custom_storage.CustomStaticStorage"},
}

# -- Logging — JSON (Docker stdout / log yig'ish / Sentry uchun) --
LOGGING = build_logging(  # noqa: F405
    debug=False,
    json_logs=True,
    log_level=config("LOG_LEVEL", default="INFO"),  # noqa: F405
)


# -- SENTRY (xato kuzatuvi: web + Celery) [P12-T1] --
# FAQAT SENTRY_DSN berilganda yoqiladi — dev/test'da o'chiq (acceptance).
# Celery worker/beat prod'da shu settings bilan ishga tushadi (docker-compose)
# -> CeleryIntegration task xatolarini ham yuboradi.
SENTRY_DSN = config("SENTRY_DSN", default="")  # noqa: F405
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=config("SENTRY_ENVIRONMENT", default="production"),  # noqa: F405
        # Deploy git SHA beradi -> xato qaysi versiyada ekani ko'rinadi (docs/ops/sentry.md)
        release=config("SENTRY_RELEASE", default="") or None,  # noqa: F405
        # PII: email/username/IP YUBORILMAYDI (faqat user.id); default
        # EventScrubber sezgir kalitlarni (password, token, secret...) o'chiradi.
        send_default_pii=False,
        # Performance trace namunasi: so'rovlarning 10% (narx/foyda balansi)
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.1, cast=float),  # noqa: F405
    )
