"""Test muhiti — tez: sqlite (xotira), tez hasher, locmem cache/email."""

from config.logging import build_logging

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "django-insecure-test-key-not-for-production"  # nosec
ALLOWED_HOSTS = ["*"]

# Tez test DB — sqlite xotirada (postgres/.env kerak emas)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Tez parol hashing
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tashqi bog'liqliksiz cache / email / storage
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Telegram — testlar .env qiymatlaridan MUSTAQIL: bo'sh kredensial
# send_telegram guard'ini ishga tushiradi (skip), tarmoqqa chiqilmaydi.
# Kerak bo'lgan test o'z qiymatini `settings` fixture bilan beradi.
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_ADMIN_CHAT_ID = ""
TMDB_API_KEY = ""  # TMDB ham: bo'sh kalit guard'i darhol TmdbError beradi, tarmoq yo'q
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# HTTPS majburlanmaydi
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Logging — testlarda jim (WARNING+)
LOGGING = build_logging(debug=False, json_logs=False, log_level="WARNING")

# Celery — testlarda sinxron (eager): task'lar worker'siz, shu jarayonda bajariladi.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
