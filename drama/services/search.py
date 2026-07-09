"""Qidiruv servisi [P8-T1] — FTS+trigram (postgres) / icontains (fallback).

Nega ikki yo'l: test suite sqlite :memory:'da (tez); postgres-maxsus xulq
drama/postgres_tests.py da (`pytest -m postgres`) — CI migrations-postgres
jobida va lokal Docker postgres'da tekshiriladi.

Postgres yo'li:
- prefix-tsquery ("sarv:*") — live-search yozish asnosida ham topadi;
- SearchRank vaznlari: A=title(uz/en/original), B=aktyorlar, C=tavsif;
- TrigramSimilarity title/original_title — xato yozuvga bardosh
  ("kdrama" ~ "k-drama"); GIN indekslar migratsiya 0028'da.
"""

from __future__ import annotations

import re

from django.db import connection
from django.db.models import Q, QuerySet

# Trigram o'xshashlik chegarasi: past — ko'p shovqin, baland — xatoni kechirmaydi.
SIMILARITY_THRESHOLD = 0.25

_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def _is_postgres() -> bool:
    return connection.vendor == "postgresql"


def _prefix_query(raw: str):
    """Foydalanuvchi matnidan XAVFSIZ prefix-tsquery: "qora sarv" -> "qora:* & sarv:*".

    Faqat \\w belgilar qoldiriladi — raw tsquery sintaksisiga injection yo'q.
    Apostrofli so'zlar ("o'tkan") ikkala tomonda ham bir xil bo'linadi:
    'simple' parser ham apostrofni ajratgich sanaydi.
    """
    from django.contrib.postgres.search import SearchQuery

    terms = [t for t in _NON_WORD_RE.sub(" ", raw).split() if t]
    if not terms:
        return None
    return SearchQuery(" & ".join(f"{t}:*" for t in terms), config="simple", search_type="raw")


def search_movies(qs: QuerySet, raw_query: str) -> QuerySet:
    """Berilgan queryset ustiga qidiruv qatlami; relevantlik tartibida.

    <2 belgi -> bo'sh natija (dropdown ham shu qoidada edi). Postgres'da
    natija rank (FTS vaznlari) + trigram o'xshashlik bo'yicha tartiblanadi —
    chaqiruvchi o'z order_by'sini QO'YMASLIGI kerak.
    """
    raw_query = (raw_query or "").strip()
    if len(raw_query) < 2:
        return qs.none()

    if not _is_postgres():
        # Fallback (sqlite dev/test): eski xulq bilan teng icontains.
        # order_by("-id") — pagination (cheksiz skroll [P5-T3]) barqaror sahifalar
        # bersin (Movie'da Meta.ordering yo'q); postgres yo'li quyida rank bilan tartiblaydi.
        return (
            qs.filter(Q(title__icontains=raw_query) | Q(original_title__icontains=raw_query))
            .distinct()
            .order_by("-id")
        )

    from django.contrib.postgres.search import SearchRank, TrigramSimilarity
    from django.db.models import F
    from django.db.models.functions import Greatest

    ts_query = _prefix_query(raw_query)
    if ts_query is None:
        return qs.none()

    return (
        qs.annotate(
            rank=SearchRank(F("search_vector"), ts_query),
            similarity=Greatest(
                TrigramSimilarity("title", raw_query),
                TrigramSimilarity("original_title", raw_query),
            ),
        )
        .filter(Q(search_vector=ts_query) | Q(similarity__gt=SIMILARITY_THRESHOLD))
        .order_by("-rank", "-similarity", "-created_at")
    )
