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
