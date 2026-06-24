"""core/notifications.py — Telegram/email yuborish (low-level) [P3-T3].

Bu funksiyalar SINXRON — ular core/tasks.py Celery wrapperlari ichida chaqiriladi
(request siklini bloklamaslik uchun). View'da to'g'ridan-to'g'ri CHAQIRMANG;
notify_telegram_task / send_email_task (.delay) ishlating.
"""

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

_TELEGRAM_TIMEOUT = 10


def send_telegram(text: str) -> bool:
    """Admin Telegram chat'iga xabar yuboradi. Sozlanmagan bo'lsa -> False (skip)."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID
    if not token or not chat_id:
        logger.warning("Telegram sozlanmagan — xabar yuborilmadi.")
        return False
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=_TELEGRAM_TIMEOUT,
    )
    resp.raise_for_status()
    return True


def send_email_message(subject: str, body: str, to: list[str]) -> int:
    """Email yuboradi (backend muhitga xos: dev console, prod SMTP)."""
    return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to, fail_silently=False)
