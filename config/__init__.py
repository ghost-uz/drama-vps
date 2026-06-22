# Celery app Django bilan birga yuklansin (@shared_task ishlashi uchun).
from .celery import app as celery_app

__all__ = ("celery_app",)
