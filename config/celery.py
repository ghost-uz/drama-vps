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
    # Premium muddati tugaganlarni har soat o'chiradi [P3-T4]
    "expire-premium": {
        "task": "users.tasks.expire_premium",
        "schedule": crontab(minute=0),
    },
    # Eski pending topuplarni har kuni 03:00 da 'rejected' qiladi [P3-T4]
    "cleanup-stale-topups": {
        "task": "users.tasks.cleanup_stale_topups",
        "schedule": crontab(hour=3, minute=0),
    },
    # Trending teglar keshini har 6 soatda yangilaydi [P3-T4]
    "recompute-trending-tags": {
        "task": "drama.tasks.recompute_trending_tags",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # Trenddagi kinolar keshini har 2 soatda yangilaydi [P8-T2]
    # (oyna asosli — teglardan tez-tez o'zgaradi)
    "recompute-trending-movies": {
        "task": "drama.tasks.recompute_trending_movies",
        "schedule": crontab(minute=0, hour="*/2"),
    },
    # Dead-man heartbeat [P12-T2] — tashqi provider ping kutadi (har 5 daqiqa)
    "monitoring-heartbeat": {
        "task": "core.tasks.heartbeat_task",
        "schedule": crontab(minute="*/5"),
    },
    # Kritik alert tekshiruvi [P12-T2] — navbat/qotgan-topup/kesh (har 10 daqiqa)
    "monitoring-alerts": {
        "task": "core.tasks.monitoring_alerts_task",
        "schedule": crontab(minute="*/10"),
    },
}


@app.task(bind=True)
def debug_task(self):
    """Test task — natija qaytaradi (result-backend tekshiruvi uchun)."""
    return f"OK from {self.request.id}"
