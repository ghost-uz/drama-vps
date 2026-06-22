"""Logging konfiguratsiyasi.

Muhitga qarab quriladi:
  - dev/test : o'qiladigan konsol formati
  - prod     : JSON (Docker stdout / log yig'ish / Sentry uchun)
build_logging() ni dev.py / prod.py / test.py chaqiradi.
"""

import json
import logging


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatlovchi — tashqi paketsiz (prod log uchun)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def build_logging(*, debug: bool, json_logs: bool, log_level: str = "INFO") -> dict:
    """LOGGING dict quradi. json_logs=True -> JSON handler, aks holda konsol."""
    handler = "json" if json_logs else "console"
    app_level = "DEBUG" if debug else "INFO"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": "{asctime} [{levelname}] {name}: {message}",
                "style": "{",
            },
            "json": {
                "()": "config.logging.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
            },
            "json": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            },
        },
        "root": {"handlers": [handler], "level": log_level},
        "loggers": {
            # WARNING+ alohida ushlanadi (request/DB shovqinini kamaytirish)
            "django": {"handlers": [handler], "level": "INFO", "propagate": False},
            "django.request": {"handlers": [handler], "level": "WARNING", "propagate": False},
            "django.db.backends": {"handlers": [handler], "level": "WARNING", "propagate": False},
            "celery": {"handlers": [handler], "level": "INFO", "propagate": False},
            "drama": {"handlers": [handler], "level": app_level, "propagate": False},
            "users": {"handlers": [handler], "level": app_level, "propagate": False},
            "funding": {"handlers": [handler], "level": app_level, "propagate": False},
            "core": {"handlers": [handler], "level": app_level, "propagate": False},
        },
    }
