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


@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def offsite_db_backup_task(self) -> str:
    """DB dumplarini GCS'ga off-site sinxronlash [R0-T4] — kunlik beat (08:30).

    db-backup sidecar 03:00 UTC (= 08:00 Tashkent) da lokal dump oladi; bu task
    30 daqiqadan keyin GCS'da YO'Q dumplarni yuklaydi (idempotent — worker
    o'lik yotgan kunlarning dumplari keyingi o'tishda to'ldiriladi).
    GCS_BACKUP_BUCKET bo'sh = o'chiq. R0 saboqlari: muvaffaqiyatsizlik JIM
    qolmaydi — 3 retry (10 daqiqa oraliq) tugagach admin Telegram alert.
    """
    from core.offsite_backup import sync_db_backups

    if not settings.GCS_BACKUP_BUCKET:
        return "off"
    try:
        result = sync_db_backups()
    except Exception as exc:
        logger.warning("offsite_db_backup_task xato: %s", exc)
        if self.request.retries >= self.max_retries:
            notify_telegram_task.delay(
                f"🚨 OFFSITE BACKUP: GCS sinxroni {self.max_retries + 1} urinishda ham "
                f"yiqildi: {exc}"
            )
            raise
        raise self.retry(exc=exc) from exc
    if result.skipped_empty:
        notify_telegram_task.delay(
            "⚠️ OFFSITE BACKUP: 0 baytli dump topildi (backup.sh qalqoni buzilganmi?): "
            + ", ".join(result.skipped_empty)
        )
    if result.local_total == 0:
        notify_telegram_task.delay(
            "⚠️ OFFSITE BACKUP: /backups bo'sh — db-backup sidecar umuman dump olmayaptimi?"
        )
        return "no-dumps"
    return f"uploaded={len(result.uploaded)} already={result.already}"


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


@shared_task(bind=True, max_retries=3, default_retry_delay=30, rate_limit="20/s")
def send_telegram_push_task(self, chat_id: int, text: str):
    """Bitta foydalanuvchiga bot xabari [V2A-T2].

    rate_limit="20/s" — Telegram Bot API ~30 msg/s chegarasidan pastda qolamiz
    (fan-out har oluvchiga alohida task ochadi, worker tezlikni o'zi jilovlaydi).
    403 (foydalanuvchi botni bloklagan) -> kanal O'CHIRILADI (chat_id tozalanadi)
    va ogohlantirish LOG'lanadi — xato jimgina yutilmaydi [AC-3]; qolgan
    xatolar retry qilinadi.
    """
    from core import telegram_bot
    from users.models import Profile

    try:
        telegram_bot.send_message(chat_id, text)
    except telegram_bot.TelegramBlocked:
        unlinked = Profile.objects.filter(telegram_chat_id=chat_id).update(telegram_chat_id=None)
        logger.warning(
            "Telegram push 403 (bot bloklangan): chat=%s -> kanal o'chirildi (%d profil)",
            chat_id,
            unlinked,
        )
    except Exception as exc:
        logger.warning("send_telegram_push_task xato (chat=%s): %s", chat_id, exc)
        raise self.retry(exc=exc) from exc
