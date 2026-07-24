"""Loyiha-darajali pytest fixture'lari [P11-T1].

Fabrikalar: drama/factories.py, users/factories.py, funding/factories.py —
testlar to'g'ridan-to'g'ri import qiladi.

Tezlik: config/settings/test.py sqlite ":memory:" ishlatadi — DB har sessiyada
RAM'da quriladi, shu bois pytest-django `--reuse-db` bu loyihada ma'nosiz
(u fayl/postgres test-DB'larini qayta ishlatish uchun).
"""

import os

import pytest
from rest_framework.test import APIClient

# [P11-T4] Playwright sync API test-thread'ida asyncio loop o'rnatadi -> Django sinxron
# ORM'ni bloklaydi (SynchronousOnlyOperation). E2E live_server testlari ORM'ni shu
# thread'da chaqiradi. Bayroq shu tekshiruvni o'chiradi (loop yo'q oddiy testlarga ta'sirsiz).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")


@pytest.fixture(autouse=True)
def _clear_cache():
    """Har test oldidan LOCMEM keshni tozalaydi [V2G-T2].

    Test DB har testda rollback bo'ladi -> PK'lar 1'dan qayta boshlanadi, lekin
    LOCMEM kesh testlar ORASIDA saqlanadi. {% cache %} kaliti pk+updated_at'ga
    tayangan fragmentlar (collection detail) Windows'ning past vaqt-granulasida
    qo'shni testlar bilan TO'QNASHIB stale HTML berardi (ordering-bog'liq flake).
    Keshni tozalash barcha kesh-bog'liq testlarni deterministik qiladi.
    """
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture
def api():
    """DRF APIClient — drama/api va users/api testlari uchun umumiy."""
    return APIClient()


@pytest.fixture
def bunny(settings):
    """Bunny Stream sozlangan test muhiti (CDN host + library id)."""
    settings.BUNNY_STREAM_CDN_HOSTNAME = "vz-test.b-cdn.net"
    settings.BUNNY_STREAM_LIBRARY_ID = "12345"
    return settings


def pytest_collection_modifyitems(config, items):
    """E2E testlarni default'da SKIP qiladi [P11-T4] — brauzer + sekin.

    `pytest -m e2e` bilan ataylab tanlansa ishga tushadi; oddiy `pytest` (va CI
    unit/coverage job'i) ularni o'tkazib yuboradi (chromium/live_server kerak emas).
    """
    markexpr = config.getoption("markexpr", "") or ""
    if "e2e" in markexpr and "not e2e" not in markexpr:
        return
    skip_e2e = pytest.mark.skip(reason="E2E: `pytest -m e2e` bilan alohida ishga tushiring")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
