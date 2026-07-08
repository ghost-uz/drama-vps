"""users/context_processors.py — ijtimoiy login flag'lari (login/register) [P6-T2].

Google/Telegram tugmalari FAQAT tegishli sozlama berilgan bo'lsa ko'rsatiladi
(dev'da kalitsiz — tugma yo'q, sindirilmagan oqim). Sof settings o'qish, DB'siz.
"""

from django.conf import settings


def social_auth(request):
    return {
        "google_login_enabled": bool(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")),
        "telegram_login_bot": getattr(settings, "TELEGRAM_LOGIN_BOT_USERNAME", ""),
    }
