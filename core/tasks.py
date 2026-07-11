"""core/tasks.py — umumiy fon vazifalari: bildirishnomalar [P3-T3].

Celery autodiscover shu fayldan topadi (core INSTALLED_APPS'da).
Tashqi servis (Telegram/SMTP) sekin/ishonchsiz -> request siklidan chiqarilgan.
"""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def notify_telegram_task(self, text: str):
    """Admin Telegram xabarini fon (Celery)da yuboradi."""
    from core.notifications import send_telegram

    try:
        send_telegram(text)
    except Exception as exc:
        logger.warning("notify_telegram_task xato: %s", exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, subject: str, body: str, recipients: list[str]):
    """Email'ni fon (Celery)da yuboradi."""
    from core.notifications import send_email_message

    if not recipients:
        return
    try:
        send_email_message(subject, body, recipients)
    except Exception as exc:
        logger.warning("send_email_task xato: %s", exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, default_retry_delay=20)
def heartbeat_task(self):
    """Dead-man switch [P12-T2]: HEARTBEAT_URL'ga davriy ping.

    healthchecks.io kabi provider ping KELMAY QOLSA alert beradi — shu bilan
    faqat web emas, butun stack (beat + worker + redis + tarmoq) kuzatiladi.
    O'zini-o'zi tekshiradigan ichki monitor bu holatni ko'ra olmasdi.
    HEARTBEAT_URL bo'sh = o'chiq (dev/test default).
    """
    url = settings.HEARTBEAT_URL
    if not url:
        return "off"
    import requests

    try:
        requests.get(url, timeout=10)
    except Exception as exc:
        logger.warning("heartbeat_task xato: %s", exc)
        raise self.retry(exc=exc) from exc
    return "ok"


@shared_task
def monitoring_alerts_task():
    """Kritik holat alertlari [P12-T2] — admin Telegram, har kalitga 1h cooldown.

    Shartlar core/monitoring.py :: collect_problems() da (navbat backlog,
    qotgan topup/shikoyat, kesh). Cooldown keshda — bir muammo har 10 daqiqada
    emas, soatiga bir marta shovqin qiladi.
    """
    from django.core.cache import cache

    from core.monitoring import collect_problems

    sent = 0
    for key, message in collect_problems():
        cooldown_key = f"monitoring:alert:{key}"
        if cache.get(cooldown_key):
            continue
        cache.set(cooldown_key, 1, 60 * 60)
        notify_telegram_task.delay(f"🚨 MONITORING: {message}")
        sent += 1
    return sent
