"""drama/services/bunny_upload.py — Bunny Stream upload API client [P3-T1].

Bunny Stream REST API: video yaratish (GUID) -> fayl yuklash (PUT) -> encoding
status poll. AccessKey header bilan autentifikatsiya.
DIQQAT: endpoint/status formati Bunny hujjatiga ko'ra; deploy'da tasdiqlanadi.
"""

import requests
from django.conf import settings

_BASE = "https://video.bunnycdn.com/library"
_TIMEOUT = 30
_UPLOAD_TIMEOUT = 600  # katta fayl uchun

# Bunny encoding status kodlari
STATUS_FINISHED = 4  # 0..3 = jarayonda, 4 = tugadi
STATUS_ERROR = 5  # 5/6 = xato


def _headers() -> dict:
    return {"AccessKey": settings.BUNNY_STREAM_API_KEY, "accept": "application/json"}


def _library_id() -> str:
    return settings.BUNNY_STREAM_LIBRARY_ID


def create_video(title: str) -> str:
    """Bunny'da bo'sh video yaratadi, GUID qaytaradi."""
    resp = requests.post(
        f"{_BASE}/{_library_id()}/videos",
        json={"title": title},
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["guid"]


def upload_video(guid: str, content: bytes) -> None:
    """Video faylni Bunny'ga yuklaydi (PUT, binary body)."""
    resp = requests.put(
        f"{_BASE}/{_library_id()}/videos/{guid}",
        data=content,
        headers={"AccessKey": settings.BUNNY_STREAM_API_KEY},
        timeout=_UPLOAD_TIMEOUT,
    )
    resp.raise_for_status()


def get_status(guid: str) -> int:
    """Video encoding statusini (0..6) qaytaradi."""
    resp = requests.get(
        f"{_BASE}/{_library_id()}/videos/{guid}",
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return int(resp.json()["status"])
