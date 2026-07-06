"""Postgres-maxsus testlar uchun sozlamalar [P8-T1].

Oddiy suite sqlite'da qoladi (tez); FTS/trigram testlari REAL postgres talab
qiladi:
  DJANGO_SETTINGS_MODULE=config.settings.test_postgres pytest -m postgres
Lokal: Docker db (compose) ishlab turishi kerak. CI: migrations-postgres job.
DB_* env o'zgaruvchilari dev/CI bilan bir xil o'qiladi (decouple).
"""

from decouple import config

from .test import *  # noqa: F403

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
