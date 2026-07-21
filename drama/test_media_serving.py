"""Test/e2e media serve route (core.media.serve_from_storage) — poster 404 shovqini yo'q.

Test sozlamalari InMemoryStorage ishlatadi (disk'da fayl yo'q). `config/urls.py`
`SERVE_MEDIA_FROM_STORAGE=True` bo'lsa media'ni storage backend orqali beradi;
aks holda `live_server` har poster URL'iga `Not Found: /media/...` warning yozardi.
"""

import pytest

from drama.factories import MovieFactory


@pytest.mark.django_db
def test_poster_media_served_from_storage(client):
    """Poster URL endi 404 emas — InMemoryStorage'dan 200 bilan oqadi (shovqinsiz)."""
    movie = MovieFactory()
    resp = client.get(movie.poster.url)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content)  # baytlar keldi (bo'sh emas)


@pytest.mark.django_db
def test_missing_media_path_returns_404(client):
    """Storage'da yo'q fayl -> 404 (Http404), server xatosi (500) EMAS."""
    resp = client.get("/media/movies/mavjud-emas.jpg")
    assert resp.status_code == 404
