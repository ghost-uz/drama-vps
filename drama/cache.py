"""Katalog keshi — versiyalangan kalitlar va invalidatsiya [P9-T1].

Yondashuv: barcha katalog-hosila kesh kalitlari bitta VERSIYA raqamini o'z
ichiga oladi (``catalog:v{n}:...``). Kontent o'zgarganda versiya +1 bo'ladi
(``bump_catalog_version``) — eski kalitlar bir zumda "ko'rinmas" bo'lib
qoladi (Redis LRU ularni o'zi siqib chiqaradi). Bu naqsh delete_many /
wildcard-scan'dan ko'ra arzon va atomik.

Invalidatsiya manbalari:
- ``drama/signals.py``: Movie/Episode/Season/Genre/Category/Tag/TopSlider
  post_save + post_delete.
- QO'LDA bump talab qiladigan joylar — ``queryset.update()`` SIGNAL
  CHAQIRMAYDI: webhook (READY), publish_scheduled_movies (beat),
  optimize_image_task (rasm nomi almashadi), admin publish/unpublish
  action'lari. Yangi ``.update()`` yo'li qo'shsangiz va u katalogda
  ko'rinadigan narsani o'zgartirsa — bump'ni unutmang (docs/ops/caching.md).

Ehtiyot chorasi: versiya kaliti evict bo'lsa versiya 1 ga "qaytadi" va juda
eski v1 kalitlar tirilishi nazariy mumkin — shuning uchun ma'lumot kalitlari
doim chekli TTL bilan yoziladi (default 6 soat).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.cache import cache

CATALOG_VERSION_KEY = "catalog:ver"
DEFAULT_TIMEOUT = 6 * 60 * 60  # 6 soat — versiya-bump asosiy invalidatsiya, TTL zaxira


def catalog_version() -> int:
    """Joriy katalog versiyasi (yo'q bo'lsa 1 dan boshlaydi)."""
    version = cache.get(CATALOG_VERSION_KEY)
    if version is None:
        cache.add(CATALOG_VERSION_KEY, 1, None)  # None = muddatsiz
        version = cache.get(CATALOG_VERSION_KEY, 1)
    return int(version)


def bump_catalog_version() -> int:
    """Versiyani +1 qiladi — barcha catalog:* kalitlar darhol eskiradi."""
    try:
        return int(cache.incr(CATALOG_VERSION_KEY))
    except ValueError:
        # Kalit hali yo'q (birinchi bump yoki kesh tozalangan)
        cache.set(CATALOG_VERSION_KEY, 2, None)
        return 2


def catalog_key(name: str) -> str:
    """Versiyalangan kalit: ``catalog:v{n}:{name}``."""
    return f"catalog:v{catalog_version()}:{name}"


def get_or_set_catalog(
    name: str, producer: Callable[[], Any], timeout: int = DEFAULT_TIMEOUT
) -> Any:
    """Versiyalangan kalitdan o'qiydi; bo'sh bo'lsa producer() natijasini yozadi.

    producer chaqiruvchida lazy queryset bo'lsa list(...) bilan evaluate
    qilib qaytarsin — keshga tayyor qiymat yoziladi.
    """
    key = catalog_key(name)
    value = cache.get(key)
    if value is None:
        value = producer()
        cache.set(key, value, timeout)
    return value
