"""
config/settings/base.py — barcha muhitlar uchun umumiy sozlamalar.

Muhitga xos qismlar: dev.py, prod.py, test.py (ular bu fayldan import qiladi).
Faol sozlama DJANGO_SETTINGS_MODULE orqali tanlanadi:
  - manage.py            -> config.settings.dev (default)
  - wsgi/asgi/passenger  -> config.settings.prod (default)
  - testlar              -> config.settings.test
"""

import mimetypes
from datetime import timedelta
from pathlib import Path

from decouple import config

# -- MIME TYPES --
mimetypes.add_type("font/woff2", ".woff2", True)
mimetypes.add_type("font/woff", ".woff", True)
mimetypes.add_type("font/ttf", ".ttf", True)
mimetypes.add_type("text/css", ".css", True)
mimetypes.add_type("application/javascript", ".js", True)

# -- YO'LLAR --
# base.py joylashuvi: config/settings/base.py
# parent=settings, parent.parent=config, parent.parent.parent=loyiha ildizi
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# -- XAVFSIZLIK --
# Dev uchun default beriladi; prod.py uni default'siz qayta o'qiydi (yo'q bo'lsa crash).
SECRET_KEY = config("SECRET_KEY", default="django-insecure-dev-only-change-me")

# -- ILOVALAR --
INSTALLED_APPS = [
    # Admin theme (eng tepada bo'lishi shart)
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    # Translation (admin'dan oldin kelishi kerak)
    "modeltranslation",
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    # Authentication
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    # Third party
    "corsheaders",
    "storages",
    "crispy_forms",
    "crispy_bootstrap5",
    "django_htmx",
    "django_celery_beat",
    # REST API (P2)
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    # Loyiha ilovalari
    "core.apps.CoreConfig",
    "drama.apps.DramaConfig",
    "funding.apps.FundingConfig",
    "users.apps.UsersConfig",
]

# -- MIDDLEWARE --
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # ENG TEPADA bo'lishi shart
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# COOP: popup orqali auth (Telegram/Google login) ishlashi uchun qat'iy
# "same-origin" emas, "allow-popups" [P10-T1]
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = True
SITE_ID = 1

# -- TEMPLATES --
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "drama.context_processors.trending_tags",
            ],
        },
    },
]

# -- MA'LUMOTLAR BAZASI --
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="drama_db"),
        "USER": config("DB_USER", default="drama_user"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# -- CACHE / SESSION (Redis) --
# REDIS_URL .env'dan. KEY_PREFIX + VERSION → kalitlar "drama:1:..." ko'rinishida.
# IGNORE_EXCEPTIONS=True: Redis ishlamasa ilova ishlayveradi (keshsiz, 500 bermaydi).
# test.py buni LocMemCache bilan, yengilroq qilib almashtiradi.
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "drama",
        "VERSION": 1,
        "TIMEOUT": 300,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    }
}
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True

# Sessiyalar: cached_db — keshdan o'qiydi, DB'ga yozadi (Redis tushsa ham yo'qolmaydi).
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "default"

# -- PAROL VALIDATSIYA --
# NOTE: P6-T1 da min_length 8 ga ko'tariladi + qo'shimcha validatorlar.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 3},
    },
]

# -- AUTENTIFIKATSIYA (allauth) --
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "none"  # NOTE: P6-T1 da 'mandatory'
ACCOUNT_USERNAME_MIN_LENGTH = 4
ACCOUNT_AUTHENTICATED_REGISTRATION_REDIRECTS = True
ACCOUNT_SIGNUP_REDIRECT_URL = "users:login"
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "drama:movie_list"
LOGOUT_REDIRECT_URL = "users:login"

# -- TIL VA VAQT --
LANGUAGE_CODE = "uz"
USE_I18N = True
USE_TZ = True
TIME_ZONE = "Asia/Tashkent"
LANGUAGES = [("uz", "Oʻzbekcha"), ("en", "English")]

# -- CRISPY FORMS --
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# -- FAYL YUKLASH CHEGARALARI --
FILE_UPLOAD_MAX_MEMORY_SIZE = 26214400  # 25 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB

# -- GOOGLE CLOUD STORAGE (CDN) konfiguratsiyasi --
# GCS faqat prod.py da yoqiladi (service-account kaliti kerak). Default (base/dev/test):
# lokal fayl tizimi — tashqi bog'liqliksiz ishlaydi.
GS_PROJECT_ID = "my-drama-uz"
GS_BUCKET_NAME = "cdn.drama.uz"
GS_QUERYSTRING_AUTH = False
GS_CUSTOM_DOMAIN = "cdn.drama.uz"
GS_CONTENT_TYPE_LIST = ["text/css", "application/javascript"]
GS_CREDENTIALS = None  # prod.py service-account kalitini yuklaydi

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# -- BUNNY STREAM CDN --
BUNNY_STREAM_LIBRARY_ID = config("BUNNY_STREAM_LIBRARY_ID", default="")
BUNNY_STREAM_CDN_HOSTNAME = config("BUNNY_STREAM_CDN_HOSTNAME", default="")
BUNNY_STREAM_API_KEY = config("BUNNY_STREAM_API_KEY", default="")
# CDN Token Authentication kaliti — signed/expiring playback URL uchun [P2-T4]
BUNNY_STREAM_TOKEN_KEY = config("BUNNY_STREAM_TOKEN_KEY", default="")
# Imzolangan URL amal qilish muddati (sekund) [P4-T1]
BUNNY_TOKEN_EXPIRY_SECONDS = config("BUNNY_TOKEN_EXPIRY_SECONDS", default=4 * 3600, cast=int)
# Token'ni mijoz IP'siga bog'lash — EHTIYOT: IPv4/IPv6 yoki proxy nomuvofiqligi
# videoni 403 qiladi; faqat docs/ops/bunny.md o'qib yoqing [P4-T1]
BUNNY_TOKEN_BIND_IP = config("BUNNY_TOKEN_BIND_IP", default=False, cast=bool)
# Webhook autentifikatsiya sirri (encoding-tugadi signali) [P3-T2]
BUNNY_WEBHOOK_SECRET = config("BUNNY_WEBHOOK_SECRET", default="")

# -- CORS / CSRF (umumiy) --
# Aniq origin ro'yxatlari muhitga xos (dev.py / prod.py).
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "x-csrftoken",
    "x-requested-with",
]
CSRF_USE_SESSIONS = False

# -- CELERY --
# Broker/result = Redis (kesh'dan boshqa DB indekslari). Windows lokal worker: --pool=solo.
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://127.0.0.1:6379/2")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_RESULT_EXTENDED = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# -- BILDIRISHNOMA (Telegram + email) [P3-T3] --
TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_ADMIN_CHAT_ID = config("TELEGRAM_ADMIN_CHAT_ID", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="admin@drama.uz")

# -- MISC --

# -- UNFOLD ADMIN --
# NOTE: django-unfold `UNFOLD` nomli sozlamani o'qiydi. Mavjud kodda `UNFOLD_SETTINGS`
# nomi ishlatilgan (ya'ni hozir QO'LLANILMAYDI). Xulq-atvorni o'zgartirmaslik uchun nom
# saqlab qolindi; keyinchalik (P14) `UNFOLD` ga o'tkazish kerak.
UNFOLD_SETTINGS = {
    "SITE_TITLE": "Drama.uz Admin",
    "SITE_HEADER": "Drama Admin",
    "SITE_SYMBOL": "movie",
    "STYLES": [
        lambda request: (
            "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200"
        ),
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
    },
}


# -- REST API (DRF + simplejwt + drf-spectacular) [P2-T1] --
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    # Katalog public -> AllowAny default; himoyalangan endpointlar view-darajada IsAuthenticated.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    # Asoslar; P2-T5 da scope'lar bilan mustahkamlanadi.
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "review": "10/hour",  # ScopedRateThrottle (Review yaratish spam himoyasi) [P2-T3]
        "search": "30/min",  # ScopedRateThrottle (qidiruv og'ir ILIKE so'rovi) [P2-T5]
        "playback": "60/min",  # ScopedRateThrottle (video playback signed URL) [P2-T4]
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Drama.uz API",
    "DESCRIPTION": "drama.uz striming platformasi REST API (mobil/SPA/integratsiyalar).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
