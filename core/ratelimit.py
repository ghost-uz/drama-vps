"""core/ratelimit.py — django-ratelimit uchun markazlashgan kalit/tezlik [P10-T2].

Tezliklar BITTA joyda — settings.RATELIMIT_RATES; view'lar decorator'da
`rate=rate, group="..."` beradi. Kalitlar Cloudflare-aware (core.http.client_ip)
— aks holda REMOTE_ADDR=edge-IP hamma foydalanuvchini bitta chelakka solardi.

Bu modul FAQAT web/HTML view'lar uchun; REST API tezliklari REST_FRAMEWORK
DEFAULT_THROTTLE_RATES da (DRF throttle) — ikkala qatlam ham default Redis
keshga yozadi.
"""

from django.conf import settings
from django.http import HttpRequest

from core.http import client_ip


def rate(group: str, request: HttpRequest) -> str | None:
    """settings.RATELIMIT_RATES[group]; yo'q bo'lsa None = cheklovsiz."""
    return settings.RATELIMIT_RATES.get(group)


def ip_key(group: str, request: HttpRequest) -> str:
    """Anonim endpointlar (login, register, qidiruv) — mijoz IP bo'yicha."""
    return client_ip(request)


def user_or_ip_key(group: str, request: HttpRequest) -> str:
    """Login talab qiladigan endpointlar — user bo'yicha (anonim: IP)."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"u:{user.pk}"
    return client_ip(request)
