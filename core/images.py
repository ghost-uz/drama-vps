"""Rasm optimizatsiyasi — sinxron PIL siqishni save()'dan Celery'ga ko'chirish (P1-T1).

`ImageOptimizationMixin` save()'da yangi yuklangan rasm maydonlarini
`transaction.on_commit` orqali Celery'ga beradi: request bloklanmaydi, WEBP siqish
fon (worker)da bajariladi.
"""

from __future__ import annotations

from functools import partial
from io import BytesIO
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image


def optimize_to_webp(
    field_file: Any, max_size: tuple[int, int] = (1280, 1280), quality: int = 80
) -> ContentFile | None:
    """ImageField faylini WEBP ContentFile'ga siqadi.

    Buzuq rasm yoki qo'llab-quvvatlanmaydigan format bo'lsa None qaytaradi —
    chaqiruvchi originalni o'zgartirmasdan qoldiradi.
    """
    try:
        pil_img: Image.Image = Image.open(field_file)
        if pil_img.mode in ("RGBA", "P", "LA"):
            pil_img = pil_img.convert("RGB")
        pil_img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        pil_img.save(buf, format="WEBP", quality=quality, optimize=True)
        buf.seek(0)
        return ContentFile(buf.read())
    except Exception:
        return None


def is_new_upload(field: Any) -> bool:
    """Maydon yangi yuklangan (storage'ga hali commit qilinmagan) faylmi.

    Django FieldFile._committed: False = yangi tayinlangan/yuklangan, True = mavjud fayl.
    Storage I/O'siz va mavjud .webp ni qayta-navbatga qo'yishdan saqlaydi.
    """
    return bool(field) and not getattr(field, "_committed", True)


class ImageOptimizationMixin:
    """save() yangi yuklangan rasm maydonlarini Celery'ga rejalashtiradi (tez, PIL'siz).

    Sub-model `OPTIMIZE_IMAGE_FIELDS` ni belgilaydi, masalan::

        OPTIMIZE_IMAGE_FIELDS = {"poster": {"max_size": (1280, 1280), "quality": 80}}

    `object` merosxo'ri (models.Model EMAS) — shuning uchun migratsiya talab qilmaydi.
    """

    OPTIMIZE_IMAGE_FIELDS: dict[str, dict[str, Any]] = {}

    def save(self, *args: Any, **kwargs: Any) -> None:
        # super().save() OLDIN aniqlaymiz — saqlangach _committed True bo'lib qoladi.
        to_optimize = [
            name for name in self.OPTIMIZE_IMAGE_FIELDS if is_new_upload(getattr(self, name, None))
        ]
        super().save(*args, **kwargs)  # type: ignore[misc]
        if not to_optimize:
            return

        from drama.tasks import optimize_image_task

        app_label = self._meta.app_label  # type: ignore[attr-defined]
        model_name = self._meta.model_name  # type: ignore[attr-defined]
        pk = self.pk  # type: ignore[attr-defined]
        for name in to_optimize:
            cfg = self.OPTIMIZE_IMAGE_FIELDS[name]
            max_size = list(cfg.get("max_size", (1280, 1280)))
            quality = cfg.get("quality", 80)
            # on_commit: fayl storage'ga yozilgach (DB commit) navbatga tushadi.
            # partial — loop o'zgaruvchisini darhol bog'laydi (lambda default-arg hack'siz).
            transaction.on_commit(
                partial(
                    optimize_image_task.delay,
                    app_label,
                    model_name,
                    pk,
                    name,
                    max_size,
                    quality,
                )
            )
