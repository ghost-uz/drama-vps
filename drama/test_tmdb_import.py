"""V2D-T1 testlari — TMDB import: mapping, dedup, slug, xato, rasm-task [API mock]."""

import pytest
from django.urls import reverse

from drama.factories import MovieFactory
from drama.models import Actor, Movie
from drama.services import tmdb
from drama.tasks import tmdb_download_images
from users.factories import UserFactory

CAST = [
    {
        "id": 100 + i,
        "name": f"Actor {i}",
        "original_name": f"배우{i}",
        "gender": 2 if i % 2 else 1,
        "profile_path": f"/p{i}.jpg" if i != 2 else None,  # 2-aktyorda rasm yo'q
    }
    for i in range(6)
]

TV_PAYLOAD = {
    "id": 71712,
    "name": "Vincenzo",
    "original_name": "빈센조",
    "overview": "Mafiya maslahatchisi Seulga qaytadi.",
    "tagline": "",
    "first_air_date": "2021-02-20",
    "origin_country": ["KR"],
    "genres": [
        {"id": 18, "name": "Drama"},
        {"id": 35, "name": "Comedy"},
        {"id": 424242, "name": "Nomalum"},  # mapping'da yo'q -> o'tkaziladi
    ],
    "episode_run_time": [80],
    "number_of_episodes": 20,
    "poster_path": "/vin.jpg",
    "credits": {"cast": CAST},
}

SEARCH_PAYLOAD = {
    "results": [
        {
            "id": 71712,
            "name": "Vincenzo",
            "original_name": "빈센조",
            "first_air_date": "2021-02-20",
            "poster_path": "/vin.jpg",
            "overview": "Mafiya...",
        },
        {
            "id": 88888,
            "name": "Vincenzo 2",
            "original_name": "",
            "first_air_date": "",
            "poster_path": None,
            "overview": "",
        },
    ]
}


@pytest.fixture
def tmdb_api(monkeypatch):
    """_request'ni yo'naltiruvchi soxta bilan almashtiradi — tarmoqqa chiqilmaydi."""
    calls = []

    def fake_request(path, params=None):
        calls.append((path, params or {}))
        if path.startswith("/search/"):
            return SEARCH_PAYLOAD
        if path == "/tv/71712":
            return TV_PAYLOAD
        raise tmdb.TmdbError("TMDB'da bunday yozuv topilmadi (404).")

    monkeypatch.setattr(tmdb, "_request", fake_request)
    return calls


# --- parse_ref ---


def test_parse_ref_variants():
    assert tmdb.parse_ref("71712") == ("tv", 71712)
    assert tmdb.parse_ref("71712", default_type="movie") == ("movie", 71712)
    assert tmdb.parse_ref("tv/71712") == ("tv", 71712)
    assert tmdb.parse_ref("movie: 27205") == ("movie", 27205)
    assert tmdb.parse_ref("https://www.themoviedb.org/tv/71712-vincenzo") == ("tv", 71712)
    with pytest.raises(tmdb.TmdbError):
        tmdb.parse_ref("nimadir boshqa")


# --- Import mapping [AC-1] ---


@pytest.mark.django_db
def test_import_creates_draft_movie(tmdb_api, django_capture_on_commit_callbacks, monkeypatch):
    queued = []
    monkeypatch.setattr("drama.tasks.tmdb_download_images.delay", lambda *a: queued.append(a))

    with django_capture_on_commit_callbacks(execute=True):
        movie = tmdb.import_movie("tv", 71712)

    assert movie.status == Movie.Status.DRAFT  # playback invarianti [AC-1]
    assert movie.tmdb_id == "tv/71712"
    assert movie.title == "Vincenzo"
    assert movie.original_title == "빈센조"
    assert movie.year == 2021
    assert movie.country == "Janubiy Koreya"
    assert movie.duration == 80
    assert movie.episodes_count == 20
    assert movie.slug == "vincenzo"
    # Janr mapping: 18 -> Drama, 35 -> Komediya; nomalum 424242 O'TKAZILADI
    assert sorted(g.name for g in movie.genres.all()) == ["Drama", "Komediya"]
    # Aktyorlar: 6 ta, main — birinchi 5 tasi
    assert movie.actors.count() == 6
    assert movie.main_actors.count() == 5
    assert Actor.objects.get(original_name="배우1").gender == "male"
    # Rasm-task navbatda: poster + profili BOR 5 aktyor (2-chisida yo'q)
    movie_pk, poster_path, actor_paths = queued[0]
    assert (movie_pk, poster_path) == (movie.pk, "/vin.jpg")
    assert len(actor_paths) == 5


# --- Dedup [AC-2, AC-3] ---


@pytest.mark.django_db
def test_import_dedup_tmdb_id(tmdb_api):
    tmdb.import_movie("tv", 71712)
    with pytest.raises(tmdb.TmdbError, match="allaqachon import"):
        tmdb.import_movie("tv", 71712)
    assert Movie.objects.filter(tmdb_id="tv/71712").count() == 1


@pytest.mark.django_db
def test_actor_dedup_original_name(tmdb_api):
    existing = Actor.objects.create(
        name="Boshqa Yozuv", original_name="배우0", slug="mavjud-aktyor"
    )
    movie = tmdb.import_movie("tv", 71712)
    assert movie.actors.filter(pk=existing.pk).exists()
    assert Actor.objects.filter(original_name="배우0").count() == 1  # dublikat YO'Q


# --- Slug to'qnashuvi [AC-2] ---


@pytest.mark.django_db
def test_slug_collision_year_suffix(tmdb_api):
    MovieFactory(slug="vincenzo")
    movie = tmdb.import_movie("tv", 71712)
    assert movie.slug == "vincenzo-2021"


@pytest.mark.django_db
def test_slug_double_collision_ref_suffix(tmdb_api):
    MovieFactory(slug="vincenzo")
    MovieFactory(slug="vincenzo-2021")
    movie = tmdb.import_movie("tv", 71712)
    assert movie.slug == "vincenzo-tv-71712"


# --- API xatolari [AC-4] ---


@pytest.mark.django_db
def test_api_404_friendly_error(tmdb_api):
    with pytest.raises(tmdb.TmdbError, match="topilmadi"):
        tmdb.import_movie("tv", 99999)
    assert Movie.objects.count() == 0


def test_unconfigured_key_friendly_error(settings):
    settings.TMDB_API_KEY = ""
    with pytest.raises(tmdb.TmdbError, match="sozlanmagan"):
        tmdb._request("/tv/1")


# --- search_or_lookup (ID yoki qidiruv) ---


def test_lookup_text_goes_to_search(tmdb_api):
    results = tmdb.search_or_lookup("Vincenzo", "tv")
    assert results[0]["tmdb_ref"] == "tv/71712"
    assert results[0]["poster_url"].endswith("/w92/vin.jpg")
    assert tmdb_api[0][0] == "/search/tv"


def test_lookup_id_fetches_details(tmdb_api):
    results = tmdb.search_or_lookup("71712", "tv")
    assert len(results) == 1
    assert results[0]["title"] == "Vincenzo"
    assert tmdb_api[0][0] == "/tv/71712"


def test_lookup_bad_id_falls_back_to_search(tmdb_api):
    results = tmdb.search_or_lookup("99999", "tv")  # bunday ID yo'q -> nom-qidiruv
    assert results
    assert [c[0] for c in tmdb_api] == ["/tv/99999", "/search/tv"]


# --- Rasm-yuklash task'i ---


@pytest.mark.django_db
def test_download_images_task_and_idempotency(monkeypatch):
    movie = MovieFactory(poster="")
    actor = Actor.objects.create(name="Song Joong-ki", original_name="송중기", slug="song-jk")

    class FakeResp:
        content = b"fake-jpeg-bytes"

        def raise_for_status(self):
            pass

    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr("drama.services.tmdb.requests.get", fake_get)

    result = tmdb_download_images.apply(args=[movie.pk, "/vin.jpg", {str(actor.pk): "/song.jpg"}])
    assert result.successful()
    movie.refresh_from_db()
    actor.refresh_from_db()
    assert movie.poster and "tmdb" in movie.poster.name
    assert actor.image and "tmdb" in actor.image.name
    assert calls == [
        "https://image.tmdb.org/t/p/original/vin.jpg",
        "https://image.tmdb.org/t/p/w500/song.jpg",
    ]

    # IDEMPOTENT: qayta chaqirilganda hech narsa qayta yuklanmaydi
    tmdb_download_images.apply(args=[movie.pk, "/vin.jpg", {str(actor.pk): "/song.jpg"}])
    assert len(calls) == 2


@pytest.mark.django_db
def test_download_retries_on_network_error(monkeypatch):
    import requests as requests_lib
    from celery.exceptions import Retry

    movie = MovieFactory(poster="")

    def down(url, timeout=None):
        raise requests_lib.ConnectionError("tarmoq yo'q")

    monkeypatch.setattr("drama.services.tmdb.requests.get", down)
    with pytest.raises(Retry):
        tmdb_download_images.apply(args=[movie.pk, "/vin.jpg", {}], throw=True)


# --- Admin view ---


@pytest.mark.django_db
def test_admin_view_search_and_import(
    client, tmdb_api, django_capture_on_commit_callbacks, monkeypatch
):
    monkeypatch.setattr("drama.tasks.tmdb_download_images.delay", lambda *a: None)
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    url = reverse("admin:drama_movie_tmdb_import_view")

    resp = client.get(url, {"q": "Vincenzo", "media_type": "tv"})
    assert resp.status_code == 200
    assert "Vincenzo" in resp.content.decode()

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, {"tmdb_ref": "tv/71712"})
    movie = Movie.objects.get(tmdb_id="tv/71712")
    assert resp.status_code == 302
    assert resp["Location"] == reverse("admin:drama_movie_change", args=[movie.pk])
    assert movie.status == Movie.Status.DRAFT


@pytest.mark.django_db
def test_admin_import_error_shows_message(client, tmdb_api):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    resp = client.post(reverse("admin:drama_movie_tmdb_import_view"), {"tmdb_ref": "tv/99999"})
    assert resp.status_code == 200
    assert any("topilmadi" in m.message for m in resp.context["messages"])
    assert Movie.objects.count() == 0


@pytest.mark.django_db
def test_admin_import_requires_add_permission(client, tmdb_api):
    client.force_login(UserFactory(is_staff=True))  # add ruxsatisiz staff
    resp = client.get(reverse("admin:drama_movie_tmdb_import_view"))
    assert resp.status_code == 403
