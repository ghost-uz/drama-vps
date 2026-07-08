"""users/services/notifications.py — sayt ichidagi bildirishnomalar (kabinet) [P6-T3].

Tashqi kanallar (Telegram/email push) core/notifications.py'da; bu MODUL faqat
DB'dagi Notification yozuvlarini boshqaradi (o'qildi/o'qilmadi holatli ro'yxat).
Yaratishning yagona nuqtasi — barcha trigger shu yerdan o'tadi.
"""

from __future__ import annotations

from users.models import Notification


def notify(recipient, kind, title, *, body="", url=""):
    """Bitta ichki bildirishnoma yaratadi.

    recipient None bo'lsa (masalan anonim harakat) jim o'tkazib yuboriladi —
    chaqiruvchilar ortiqcha tekshiruvsiz chaqira olishi uchun.
    """
    if recipient is None:
        return None
    return Notification.objects.create(
        recipient=recipient, kind=kind, title=title, body=body, url=url
    )


def unread_count(user) -> int:
    """Kirgan foydalanuvchining o'qilmagan bildirishnomalari soni (nav badge)."""
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(recipient=user, is_read=False).count()


def mark_all_read(user) -> int:
    """Barcha o'qilmaganlarni o'qilgan qiladi; yangilangan yozuvlar sonini qaytaradi."""
    return Notification.objects.filter(recipient=user, is_read=False).update(is_read=True)
