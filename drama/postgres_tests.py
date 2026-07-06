"""P8-T1: FTS+trigram postgres-maxsus testlari.

Ishga tushirish (oddiy sqlite suite bularni SKIP qiladi):
  lokal:  Docker db up + DJANGO_SETTINGS_MODULE=config.settings.test_postgres
          pytest -m postgres
  CI:     migrations-postgres job (avtomatik qadam)
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse
from PIL import Image

from drama.factories import MovieFactory
from drama.models import Actor, Movie
from drama.services.search import search_movies
from drama.tasks import update_search_vector

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="real postgres kerak (sqlite'da fallback testlari drama/tests.py da)",
    ),
]


def _image(name="a.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def _published(**kwargs):
    """Movie yaratib, FTS vektorini SINXRON quradi (test aniqligi uchun)."""
    movie = MovieFactory(**kwargs)
    update_search_vector(movie.pk)
    return movie


def test_fts_title_ranks_above_description():
    """Acceptance: reytinglangan natija — A vazn (title) C (tavsif)dan yuqori."""
    title_hit = _published(title="Sarv qissasi")
    desc_hit = _published(title="Boshqa nom", description="sarv daraxti haqida hikoya")

    res = list(search_movies(Movie.objects.published(), "sarv"))
    assert [m.pk for m in res[:2]] == [title_hit.pk, desc_hit.pk]


def test_trigram_tolerates_typo():
    """Acceptance: 'kdrama' ~ 'K-Drama' trigram orqali topiladi."""
    movie = _published(title="K-Drama Hayot")
    res = list(search_movies(Movie.objects.published(), "kdrama"))
    assert movie.pk in [m.pk for m in res]


def test_prefix_matches_while_typing():
    """Yozish asnosida ('sarvi') to'liq so'z ('Sarvinoz') topiladi — live-search."""
    movie = _published(title="Sarvinoz")
    res = list(search_movies(Movie.objects.published(), "sarvi"))
    assert movie.pk in [m.pk for m in res]


def test_actor_names_are_searchable():
    """B vazn: aktyor ismi bo'yicha kino topiladi."""
    actor = Actor.objects.create(name="Kim Soo Hyun", image=_image())
    movie = MovieFactory(title="Aktyorli film")
    movie.actors.add(actor)
    update_search_vector(movie.pk)

    res = list(search_movies(Movie.objects.published(), "soo hyun"))
    assert movie.pk in [m.pk for m in res]


def test_signal_populates_vector(django_capture_on_commit_callbacks):
    """post_save -> on_commit -> Celery(eager) task vektorni quradi."""
    with django_capture_on_commit_callbacks(execute=True):
        movie = MovieFactory(title="Signal Film")
    movie.refresh_from_db()
    assert movie.search_vector


def test_live_search_endpoint_uses_fts(client):
    """Acceptance: live-search shu mexanizmda — xato yozuv ham natija beradi."""
    from django.core.cache import cache

    cache.clear()  # live_search 30/m chelagi
    _published(title="Endpoint Drama")
    resp = client.get(reverse("drama:live_search"), {"q": "endpont"})
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()["results"]]
    assert "Endpoint Drama" in titles
    cache.clear()
