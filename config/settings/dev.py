"""Dev muhiti — lokal ishlab chiqish. DEBUG, konsol email, HTTPS majburlanmaydi."""

from config.logging import build_logging

from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]

# Email — konsolga chiqadi
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "admin@drama.uz"

# Lokal HTTP ishlashi uchun HTTPS/secure-cookie majburlanmaydi
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "SAMEORIGIN"

INTERNAL_IPS = ["127.0.0.1"]

# CORS / CSRF — lokal manzillar
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Logging — o'qiladigan konsol formati
LOGGING = build_logging(debug=True, json_logs=False)
