"""core/http.py — HTTP yordamchilar [P10-T2]."""

from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str:
    """Haqiqiy mijoz IP — Cloudflare/proxy ortida ham.

    REMOTE_ADDR Cloudflare ortida CF edge IP bo'ladi — rate-limit barcha
    foydalanuvchilarni bitta chelakka solib qo'yar edi. CF-Connecting-IP
    eng ishonchli manba; X-Forwarded-For birinchi qiymati fallback.
    """
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for", ""
    )
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
