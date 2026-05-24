"""
Django settings for config project.
drama.uz - Production Settings (Optimized)
"""

import os
import mimetypes
from pathlib import Path
from google.oauth2 import service_account
from decouple import config

# ==============================================================================
# 1. MIME TYPES
# ==============================================================================
mimetypes.add_type("font/woff2", ".woff2", True)
mimetypes.add_type("font/woff", ".woff", True)
mimetypes.add_type("font/ttf", ".ttf", True)
mimetypes.add_type("text/css", ".css", True)
mimetypes.add_type("application/javascript", ".js", True)

# ==============================================================================
# 2. ASOSIY YO'LLAR
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================================================================
# 3. XAVFSIZLIK (Security)
# ==============================================================================
SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    'drama.uz',
    'www.drama.uz',
    '207.154.194.231',
    'localhost',
    '127.0.0.1',
]

# ==============================================================================
# 4. ILOVALAR (Installed Apps)
# ==============================================================================
INSTALLED_APPS = [
    # 1. Admin theme (eng tepada bo'lishi SHART)
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",

    # 2. Translation (admin-dan oldin kelishi kerak)
    "modeltranslation",

    # 3. Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.sitemaps',

    # 4. Authentication
    'allauth',
    'allauth.account',
    'allauth.socialaccount',

    # 5. Third party
    'corsheaders',
    'storages',
    'crispy_forms',
    'crispy_bootstrap5',
    'django_htmx',

    # 6. Loyiha ilovalari
    'drama.apps.DramaConfig',
    'funding.apps.FundingConfig',
    'users.apps.UsersConfig',
]

# ==============================================================================
# 5. MIDDLEWARE
# ==============================================================================
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',          # ← ENG TEPADA bo'lishi shart
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

# ==============================================================================
# 6. SSL VA HTTPS SOZLAMALARI
# ==============================================================================
# Cloudflare orqali kelgan real protokolni aniqlash
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HTTP → HTTPS avtomatik yo'naltirish
SECURE_SSL_REDIRECT = True

# HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = 31536000        # 1 yil
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False           # Preload list uchun tayyor bo'lganda True qiling

# ==============================================================================
# 7. XAVFSIZLIK HEADERLARI
# ==============================================================================
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Telegram WebView va Mini App iframe uchun ALLOWALL qilinadi!
X_FRAME_OPTIONS = 'ALLOWALL'

# ==============================================================================
# 8. COOKIE SOZLAMALARI (Telegram WebView uchun optimallashtirilgan)
# ==============================================================================
# SameSite=None → cross-site (Telegram WebView) da cookie ishlashi uchun
# Secure=True   → SameSite=None bo'lsa bu MAJBURIY
CSRF_COOKIE_SAMESITE = 'None'
SESSION_COOKIE_SAMESITE = 'None'
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False          # JS orqali CSRF token o'qish uchun
CSRF_COOKIE_DOMAIN = '.drama.uz'      # Barcha subdomenlar uchun

# ==============================================================================
# 9. CORS SOZLAMALARI
# ==============================================================================
CORS_ALLOWED_ORIGINS = [
    'https://drama.uz',
    'https://www.drama.uz',
    'https://web.telegram.org',       # Telegram WebView
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'authorization',
    'content-type',
    'x-csrftoken',
    'x-requested-with',
]

# ==============================================================================
# 10. CSRF SOZLAMALARI
# ==============================================================================
CSRF_TRUSTED_ORIGINS = [
    'https://drama.uz',
    'https://www.drama.uz',
    'https://web.telegram.org',  # BUNi QO'SHISH SHART
]
CSRF_USE_SESSIONS = False

# ==============================================================================
# 11. URL VA BOSHQA ASOSIY SOZLAMALAR
# ==============================================================================
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
APPEND_SLASH = True
SITE_ID = 1

# ==============================================================================
# 12. TEMPLATES
# ==============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'drama.context_processors.trending_tags',
            ],
        },
    },
]

# ==============================================================================
# 13. MA'LUMOTLAR BAZASI
# ==============================================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='drama_db'),
        'USER': config('DB_USER', default='drama_user'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# ==============================================================================
# 14. PAROL VALIDATSIYA
# ==============================================================================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 3},
    },
]

# ==============================================================================
# 15. AUTENTIFIKATSIYA (Allauth)
# ==============================================================================
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ACCOUNT_LOGIN_METHODS = {'username'}
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_USERNAME_MIN_LENGTH = 4
ACCOUNT_AUTHENTICATED_REGISTRATION_REDIRECTS = True
ACCOUNT_SIGNUP_REDIRECT_URL = 'users:login'

LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = 'drama:movie_list'
LOGOUT_REDIRECT_URL = 'users:login'

# ==============================================================================
# 16. TIL VA VAQT
# ==============================================================================
LANGUAGE_CODE = 'uz'
USE_I18N = True
USE_TZ = True
TIME_ZONE = 'Asia/Tashkent'

LANGUAGES = [
    ('uz', 'Oʻzbekcha'),
    ('en', 'English'),
]

# ==============================================================================
# 17. EMAIL
# ==============================================================================
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'admin@drama.uz'

# ==============================================================================
# 18. CRISPY FORMS
# ==============================================================================
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ==============================================================================
# 19. FAYL YUKLASH CHEGARALARI
# ==============================================================================
FILE_UPLOAD_MAX_MEMORY_SIZE = 26214400    # 25 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB

# ==============================================================================
# 20. GOOGLE CLOUD STORAGE (CDN)
# ==============================================================================
GS_PROJECT_ID = 'my-drama-uz'
GS_BUCKET_NAME = 'cdn.drama.uz'
GS_QUERYSTRING_AUTH = False
GS_CUSTOM_DOMAIN = 'cdn.drama.uz'
GS_CONTENT_TYPE_LIST = ['text/css', 'application/javascript']

GS_CREDENTIALS = service_account.Credentials.from_service_account_file(
    os.path.join(BASE_DIR, 'drama-key-v2.json')
)

STATIC_URL = f'https://{GS_CUSTOM_DOMAIN}/static/'
MEDIA_URL = f'https://{GS_CUSTOM_DOMAIN}/media/'

STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

STORAGES = {
    "default": {
        "BACKEND": "config.custom_storage.CustomMediaStorage",
    },
    "staticfiles": {
        "BACKEND": "config.custom_storage.CustomStaticStorage",
    },
}

# ==============================================================================
# 21. DEFAULT AUTO FIELD
# ==============================================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==============================================================================
# 22. UNFOLD ADMIN SOZLAMALARI
# ==============================================================================
UNFOLD_SETTINGS = {
    "SITE_TITLE": "Drama.uz Admin",
    "SITE_HEADER": "Drama Admin",
    "SITE_SYMBOL": "movie",
    "STYLES": [
        lambda request: "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200",
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50":  "250 245 255",
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