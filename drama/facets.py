"""drama/facets.py — explore faceted filtr sonlari [P8-T3].

Har facet qiymati yonida "nechta kino" ko'rsatiladi. Sonlar GLOBAL (joriy
tanlovga bog'liq emas) — bu keshlanadigan va oddiy yondashuv; kesh
versiyalangan (catalog:v{n}) — Movie o'zgarsa signal bump darhol yangilaydi.

Barcha son `published()` ko'rinish invariantidan olinadi (qoralama sizmaydi).
Har funksiya keshga tayyor list qaytaradi.
"""

from __future__ import annotations

from django.db.models import Count

from drama.cache import get_or_set_catalog
from drama.models import Movie


def genre_facets() -> list[dict]:
    """[{slug, name, count}] — har janrdagi chop etilgan kinolar soni."""
    return get_or_set_catalog(
        "genre_facets",
        lambda: list(
            Movie.objects.published()
            .exclude(genres__isnull=True)
            .values("genres__slug", "genres__name")
            .annotate(count=Count("id", distinct=True))
            .order_by("genres__name")
        ),
    )


def country_facets() -> list[dict]:
    """[{country, count}] — davlat bo'yicha kino soni."""
    return get_or_set_catalog(
        "country_facets",
        lambda: list(
            Movie.objects.published()
            .exclude(country="")
            .values("country")
            .annotate(count=Count("id"))
            .order_by("country")
        ),
    )


def year_facets() -> list[dict]:
    """[{year, count}] — yil bo'yicha kino soni (yangidan eskiga)."""
    return get_or_set_catalog(
        "year_facets",
        lambda: list(
            Movie.objects.published().values("year").annotate(count=Count("id")).order_by("-year")
        ),
    )
