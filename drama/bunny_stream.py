"""
Bunny Stream CDN — URL generator service.

Barcha URL lar faqat Video ID va settings orqali dinamik yaratiladi.
Ma'lumotlar bazasida faqat bunny_video_id saqlanadi.

[P4-T1] Token Authentication: BUNNY_STREAM_TOKEN_KEY o'rnatilgan bo'lsa BARCHA
video URL'lar imzolanadi (token + token_path + expires) va panelda Token Auth
yoqilgach Bunny imzosiz so'rovlarni rad etadi (docs/ops/bunny.md). Kalit bo'sh
bo'lsa (dev/test) URL'lar imzosiz qaytadi — token auth o'chiq muhit bilan mos.
"""

import base64
import hashlib
import time
from urllib.parse import quote

from django.conf import settings


def _cdn_host() -> str:
    return getattr(settings, "BUNNY_STREAM_CDN_HOSTNAME", "")


def _library_id() -> str:
    return getattr(settings, "BUNNY_STREAM_LIBRARY_ID", "")


def _token_key() -> str:
    return getattr(settings, "BUNNY_STREAM_TOKEN_KEY", "")


def is_configured() -> bool:
    """Bunny Stream sozlamalari to'liq kiritilganligini tekshiradi."""
    return bool(_cdn_host() and _library_id())


def token_expiry_seconds() -> int:
    """Imzolangan URL amal qilish muddati (default 4 soat)."""
    return getattr(settings, "BUNNY_TOKEN_EXPIRY_SECONDS", 4 * 3600)


def token_user_ip(request) -> str:
    """Token'ga bog'lanadigan mijoz IP — faqat BUNNY_TOKEN_BIND_IP yoqilganda.

    Default O'CHIQ: sahifa Django'ga bir IP orqali kelib (IPv6/proxy), CDN'ga
    boshqa IP (IPv4, mobil rotatsiya) bilan murojaat qilinsa video 403 bo'ladi.
    Yoqishdan oldin docs/ops/bunny.md dagi ogohlantirishni o'qing.
    """
    if not getattr(settings, "BUNNY_TOKEN_BIND_IP", False):
        return ""
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for", ""
    )
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _sign_token(signature_path: str, expires: int, user_ip: str, parameter_data: str) -> str:
    """Bunny CDN Token Authentication imzosi (rasmiy algoritm, URL-safe base64).

    hashable = key + signature_path + expires + user_ip + parameter_data
    """
    hashable = f"{_token_key()}{signature_path}{expires}{user_ip}{parameter_data}"
    raw = hashlib.sha256(hashable.encode()).digest()
    return base64.b64encode(raw).decode().replace("+", "-").replace("/", "_").replace("=", "")


def _signed_cdn_url(video_id: str, filename: str, expiry_seconds: int | None, user_ip: str) -> str:
    """CDN fayl URL'i; kalit bo'lsa video PAPKASI bo'yicha token qo'shadi.

    token_path = "/{video_id}/" — HLS playlist ichidagi sifat-playlist va
    segment fayllari ham shu token bilan o'tadi (Bunny m3u8 ichidagi URL'larga
    token'ni o'zi ko'chiradi). Faqat fayl yo'lini imzolasak playlist ochilib,
    segmentlar 403 bo'lar edi.
    """
    base = f"https://{_cdn_host()}/{video_id}/{filename}"
    if not _token_key():
        return base  # dev/sozlanmagan: imzosiz
    token_path = f"/{video_id}/"
    expires = int(time.time()) + (expiry_seconds or token_expiry_seconds())
    token = _sign_token(token_path, expires, user_ip, f"token_path={token_path}")
    return f"{base}?token={token}&token_path={quote(token_path, safe='')}&expires={expires}"


def hls_url(video_id: str, expiry_seconds: int | None = None, user_ip: str = "") -> str:
    """HLS Playlist URL — adaptive bitrate streaming uchun (asosiy). Imzolangan."""
    return _signed_cdn_url(video_id, "playlist.m3u8", expiry_seconds, user_ip)


def direct_url(
    video_id: str, resolution: int = 720, expiry_seconds: int | None = None, user_ip: str = ""
) -> str:
    """Direct MP4 URL — muayyan sifat uchun. Imzolangan."""
    return _signed_cdn_url(video_id, f"play_{resolution}p.mp4", expiry_seconds, user_ip)


def thumbnail_url(video_id: str, expiry_seconds: int | None = None, user_ip: str = "") -> str:
    """Video thumbnail rasmi URL. Imzolangan (token auth butun zonani qamraydi)."""
    return _signed_cdn_url(video_id, "thumbnail.jpg", expiry_seconds, user_ip)


def preview_url(video_id: str, expiry_seconds: int | None = None, user_ip: str = "") -> str:
    """Video preview animatsiyasi (WebP) URL. Imzolangan."""
    return _signed_cdn_url(video_id, "preview.webp", expiry_seconds, user_ip)


def embed_url(video_id: str, expiry_seconds: int | None = None) -> str:
    """Bunny iframe embed player URL (ixtiyoriy).

    Embed View Token Authentication: token = SHA256_HEX(key + video_id + expires)
    — CDN token'dan BOSHQA format (iframe.mediadelivery.net shuni kutadi).
    """
    base = f"https://iframe.mediadelivery.net/embed/{_library_id()}/{video_id}"
    key = _token_key()
    if not key:
        return base
    expires = int(time.time()) + (expiry_seconds or token_expiry_seconds())
    token = hashlib.sha256(f"{key}{video_id}{expires}".encode()).hexdigest()
    return f"{base}?token={token}&expires={expires}"


def get_all_urls(video_id: str, expiry_seconds: int | None = None, user_ip: str = "") -> dict:
    """Video ID dan barcha URL larni bir dict sifatida qaytaradi (imzolangan)."""
    if not video_id or not is_configured():
        return {}
    return {
        "hls": hls_url(video_id, expiry_seconds, user_ip),
        "play_720": direct_url(video_id, 720, expiry_seconds, user_ip),
        "play_1080": direct_url(video_id, 1080, expiry_seconds, user_ip),
        "thumbnail": thumbnail_url(video_id, expiry_seconds, user_ip),
        "preview": preview_url(video_id, expiry_seconds, user_ip),
        "embed": embed_url(video_id, expiry_seconds),
    }


def signed_hls_url(video_id: str, expiry_seconds: int | None = None, user_ip: str = "") -> str:
    """[P2-T4] nomi saqlangan alias — endi hls_url'ning o'zi ham imzolaydi (P4-T1)."""
    return hls_url(video_id, expiry_seconds, user_ip)
