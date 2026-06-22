"""
Bunny Stream CDN — URL generator service.

Barcha URL lar faqat Video ID va settings orqali dinamik yaratiladi.
Ma'lumotlar bazasida faqat bunny_video_id saqlanadi.
"""

from django.conf import settings


def _cdn_host() -> str:
    return getattr(settings, "BUNNY_STREAM_CDN_HOSTNAME", "")


def _library_id() -> str:
    return getattr(settings, "BUNNY_STREAM_LIBRARY_ID", "")


def is_configured() -> bool:
    """Bunny Stream sozlamalari to'liq kiritilganligini tekshiradi."""
    return bool(_cdn_host() and _library_id())


def hls_url(video_id: str) -> str:
    """HLS Playlist URL — adaptive bitrate streaming uchun (asosiy)."""
    return f"https://{_cdn_host()}/{video_id}/playlist.m3u8"


def direct_url(video_id: str, resolution: int = 720) -> str:
    """Direct MP4 URL — muayyan sifat uchun."""
    return f"https://{_cdn_host()}/{video_id}/play_{resolution}p.mp4"


def thumbnail_url(video_id: str) -> str:
    """Video thumbnail rasmi URL."""
    return f"https://{_cdn_host()}/{video_id}/thumbnail.jpg"


def preview_url(video_id: str) -> str:
    """Video preview animatsiyasi (WebP) URL."""
    return f"https://{_cdn_host()}/{video_id}/preview.webp"


def embed_url(video_id: str) -> str:
    """Bunny iframe embed player URL (ixtiyoriy)."""
    return f"https://iframe.mediadelivery.net/embed/{_library_id()}/{video_id}"


def get_all_urls(video_id: str) -> dict:
    """Video ID dan barcha URL larni bir dict sifatida qaytaradi."""
    if not video_id or not is_configured():
        return {}
    return {
        "hls": hls_url(video_id),
        "play_720": direct_url(video_id, 720),
        "play_1080": direct_url(video_id, 1080),
        "thumbnail": thumbnail_url(video_id),
        "preview": preview_url(video_id),
        "embed": embed_url(video_id),
    }
