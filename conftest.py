"""Loyiha-darajali pytest fixture'lari [P11-T1].

Fabrikalar: drama/factories.py, users/factories.py, funding/factories.py —
testlar to'g'ridan-to'g'ri import qiladi.

Tezlik: config/settings/test.py sqlite ":memory:" ishlatadi — DB har sessiyada
RAM'da quriladi, shu bois pytest-django `--reuse-db` bu loyihada ma'nosiz
(u fayl/postgres test-DB'larini qayta ishlatish uchun).
"""

import pytest
from rest_framework.test import APIClient


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
