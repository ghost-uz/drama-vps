"""Fayl yuklash xavfsizligi — validatorlar va xavfsiz nomlash (P10-T3).

Chegara qatlami: model maydonidagi ``validators=[...]`` web-forma
(``full_clean``), admin va DRF serializer'larda BIRDAY ishlaydi — fayl
diskka yozilishidan OLDIN. ``optimize_to_webp`` (Celery) bosqichiga tayanib
bo'lmaydi: u saqlab bo'lingan faylni siqadi va xatoni jim yutadi.

Muhim: storage'dagi mavjud (committed) fayllar qayta tekshirilmaydi — aks
holda har bir aloqasiz saqlash (masalan, admin sarlavha tahriri) faylni
storage'dan qayta o'qir va eski fayllar yangi qoidalarda yiqilib, tahrirni
bloklab qo'yardi. Faqat YANGI yuklash tekshiriladi.
"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.deconstruct import deconstructible
from PIL import Image

# Kengaytma <-> haqiqiy PIL formati. Ro'yxatdan tashqari turlar (GIF, BMP,
# TIFF, SVG...) qabul qilinmaydi — hujum yuzasi tor, optimize_to_webp bilan mos.
IMAGE_EXT_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}

# Video kontenti sehrli baytlar bilan tasdiqlanadi (kengaytmaga ishonmaymiz):
# (offset, signature) juftliklari — hammasi mos kelishi shart.
VIDEO_EXT_MAGIC: dict[str, list[tuple[int, bytes]]] = {
    ".mp4": [(4, b"ftyp")],
    ".m4v": [(4, b"ftyp")],
    ".mov": [(4, b"ftyp")],
    ".mkv": [(0, b"\x1a\x45\xdf\xa3")],  # EBML (Matroska)
    ".webm": [(0, b"\x1a\x45\xdf\xa3")],
    ".avi": [(0, b"RIFF"), (8, b"AVI ")],
}


def _is_committed(file: Any) -> bool:
    """Storage'dagi mavjud FieldFile'mi (yangi yuklash EMAS).

    FieldFile._committed: False = yangi tayinlangan, True = saqlangan fayl.
    DRF UploadedFile'da atribut yo'q -> False -> tekshiriladi (to'g'ri yo'nalish).
    """
    return bool(getattr(file, "_committed", False))


@deconstructible
class ImageFileValidator:
    """Rasm yuklash: hajm cheki, kengaytma-kontent mosligi, piksel-bomba.

    Django'ning forms.ImageField'i PIL bilan "ochiladimi"nigina tekshiradi;
    bu validator qo'shadi: per-fayl hajm cheki (global chegara 500MB — video
    uchun), soxta kengaytma rad (masalan PNG tarkibli .jpg) va
    dekompressiya-bomba himoyasi (PIL header'dan o'lcham dekodlashsiz o'qiladi).
    """

    def __init__(self, max_mb: int = 10, max_pixels: int = 50_000_000) -> None:
        self.max_mb = max_mb
        self.max_pixels = max_pixels

    def __call__(self, file: Any) -> None:
        if _is_committed(file):
            return

        size = getattr(file, "size", 0) or 0
        if size > self.max_mb * 1024 * 1024:
            raise ValidationError(
                f"Rasm hajmi {self.max_mb} MB dan oshmasligi kerak "
                f"(yuklangan: {size / (1024 * 1024):.1f} MB).",
                code="image_too_large",
            )

        ext = Path(getattr(file, "name", "") or "").suffix.lower()
        expected_format = IMAGE_EXT_FORMATS.get(ext)
        if expected_format is None:
            allowed = ", ".join(sorted(IMAGE_EXT_FORMATS))
            raise ValidationError(f"Ruxsat etilgan rasm turlari: {allowed}.", code="image_ext")

        try:
            file.seek(0)
            with Image.open(file) as img:
                real_format = img.format
                width, height = img.size
        except Image.DecompressionBombError as exc:
            raise ValidationError(
                "Rasm o'lchami xavfli darajada katta (dekompressiya-bomba).",
                code="image_bomb",
            ) from exc
        except Exception as exc:
            raise ValidationError(
                "Fayl haqiqiy rasm emas yoki buzilgan.", code="image_invalid"
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                file.seek(0)

        if real_format != expected_format:
            raise ValidationError(
                f"Fayl kengaytmasi ({ext}) haqiqiy tarkibiga ({real_format}) mos emas.",
                code="image_mismatch",
            )
        if width * height > self.max_pixels:
            raise ValidationError(
                f"Rasm o'lchami juda katta ({width}x{height} piksel). "
                f"Chegara: {self.max_pixels // 1_000_000} megapiksel.",
                code="image_bomb",
            )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ImageFileValidator)
            and self.max_mb == other.max_mb
            and self.max_pixels == other.max_pixels
        )


@deconstructible
class VideoFileValidator:
    """Video yuklash: kengaytma allowlist + sehrli baytlar + hajm cheki.

    Episode.video_file Bunny'ga ketguncha /media/ (nginx ommaviy) ostida
    yotadi — kontent tekshiruvi HTML/skript faylni video niqobida yuklab,
    shu domenda servis qildirishning (stored-XSS) oldini oladi.
    """

    def __init__(self, max_mb: int = 500) -> None:
        self.max_mb = max_mb

    def __call__(self, file: Any) -> None:
        if _is_committed(file):
            return

        size = getattr(file, "size", 0) or 0
        if size > self.max_mb * 1024 * 1024:
            raise ValidationError(
                f"Video hajmi {self.max_mb} MB dan oshmasligi kerak.",
                code="video_too_large",
            )

        ext = Path(getattr(file, "name", "") or "").suffix.lower()
        signatures = VIDEO_EXT_MAGIC.get(ext)
        if signatures is None:
            allowed = ", ".join(sorted(VIDEO_EXT_MAGIC))
            raise ValidationError(f"Ruxsat etilgan video turlari: {allowed}.", code="video_ext")

        try:
            file.seek(0)
            header = file.read(16)
        except Exception as exc:
            raise ValidationError("Video faylni o'qib bo'lmadi.", code="video_unreadable") from exc
        finally:
            with contextlib.suppress(Exception):
                file.seek(0)

        for offset, sig in signatures:
            if header[offset : offset + len(sig)] != sig:
                raise ValidationError(
                    "Fayl tarkibi video formatiga mos emas (soxta kengaytma?).",
                    code="video_mismatch",
                )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VideoFileValidator) and self.max_mb == other.max_mb


@deconstructible
class RandomFileName:
    """upload_to: ``prefix/YYYY/MM/<uuid>.ext`` — taxmin qilib bo'lmaydigan nom.

    /media/ nginx orqali ommaviy servis qilinadi; chek (shaxsiy ma'lumot)
    asl nomda saqlansa URL'ni taxminlash mumkin. UUID nom + asl nomni
    yo'qotish ham maxfiylik, ham fayl-nom tozaligini (unicode/bo'shliq/
    maxsus belgilar) bir yo'la hal qiladi. Kengaytma saqlanadi — nginx
    Content-Type shundan aniqlaydi.
    """

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix.strip("/")

    def __call__(self, instance: Any, filename: str) -> str:
        ext = Path(filename).suffix.lower()[:10]
        return f"{self.prefix}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RandomFileName) and self.prefix == other.prefix


@deconstructible
class SubtitleFileValidator:
    """VTT subtitr yuklash [V2E-T1]: faqat .vtt + WEBVTT magic + hajm cheki.

    P10-T3 uslubi: kontent tekshiruvi HTML/skriptni subtitr niqobida yuklab,
    ommaviy CDN ostida servis qildirishning (stored-XSS) oldini oladi.
    """

    def __init__(self, max_mb: int = 2) -> None:
        self.max_mb = max_mb

    def __call__(self, file: Any) -> None:
        if _is_committed(file):
            return

        size = getattr(file, "size", 0) or 0
        if size > self.max_mb * 1024 * 1024:
            raise ValidationError(
                f"Subtitr hajmi {self.max_mb} MB dan oshmasligi kerak.",
                code="vtt_too_large",
            )

        ext = Path(getattr(file, "name", "") or "").suffix.lower()
        if ext != ".vtt":
            raise ValidationError("Faqat .vtt (WebVTT) fayl qabul qilinadi.", code="vtt_ext")

        try:
            file.seek(0)
            head = file.read(16)
        except Exception as exc:
            raise ValidationError("Subtitr faylni o'qib bo'lmadi.", code="vtt_unreadable") from exc
        finally:
            with contextlib.suppress(Exception):
                file.seek(0)

        # UTF-8 BOM bilan kelishi mumkin — undan keyin WEBVTT bo'lishi SHART
        if head.startswith(b"\xef\xbb\xbf"):
            head = head[3:]
        if not head.startswith(b"WEBVTT"):
            raise ValidationError(
                "Fayl WebVTT emas (WEBVTT sarlavhasi topilmadi).", code="vtt_magic"
            )
