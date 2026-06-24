"""core/tasks.py — umumiy fon vazifalari: bildirishnomalar [P3-T3].

Celery autodiscover shu fayldan topadi (core INSTALLED_APPS'da).
Tashqi servis (Telegram/SMTP) sekin/ishonchsiz -> request siklidan chiqarilgan.
"""

import logging

from celery import shared_task

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
