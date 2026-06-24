"""Celery ilovasi — drama loyihasi.

Worker:  celery -A config worker -l info          (Windows lokal: --pool=solo)
Beat:    celery -A config beat -l info
Sozlamalar settings'da CELERY_ prefiksi bilan (namespace="CELERY").
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("drama")

# Barcha CELERY_* sozlamalarni Django settings'dan oladi.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Har app'dagi tasks.py avtomatik topiladi (autodiscover).
app.autodiscover_tasks()

# Davriy (beat) vazifalar. DatabaseScheduler buni startup'da DB'ga sinxronlaydi.
app.conf.beat_schedule = {
    # Vaqti yetgan rejalashtirilgan kinolarni har daqiqa 'published' ga o'tkazadi.
    "publish-scheduled-movies": {
        "task": "drama.tasks.publish_scheduled_movies",
        "schedule": crontab(minute="*"),
    },
}


@app.task(bind=True)
def debug_task(self):
    """Test task — natija qaytaradi (result-backend tekshiruvi uchun)."""
    return f"OK from {self.request.id}"
