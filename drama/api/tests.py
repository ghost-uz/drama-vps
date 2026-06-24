"""drama/api/ katalog API testlari [P2-T2]."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from drama.models import Episode, Genre, Movie, Season


@pytest.fixture
def api():
    return APIClient()


def _uploaded(name="p.jpg"):
    return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/jpeg")


def _movie(title, **kwargs):
    defaults = {"description": "x", "country": "KR", "poster": _uploaded()}
    defaults.update(kwargs)
    return Movie.objects.create(title=title, **defaults)


@pytest.mark.django_db
def test_movie_list(api):
    _movie("A")
    _movie("B")
    resp = api.get("/api/v1/movies/")
    assert resp.status_code == 200
    assert resp.data["count"] == 2
    assert len(resp.data["results"]) == 2


@pytest.mark.django_db
def test_movie_list_excludes_draft(api):
    _movie("Pub")
    _movie("Draft", status=Movie.Status.DRAFT)
    resp = api.get("/api/v1/movies/")
    titles = [m["title"] for m in resp.data["results"]]
    assert "Pub" in titles
    assert "Draft" not in titles


@pytest.mark.django_db
def test_movie_detail_nested_seasons_episodes(api):
    movie = _movie("Serial")
    s1 = Season.objects.create(movie=movie, number=1)
    Episode.objects.create(movie=movie, season=s1, title="Ep1", episode_number=1)
    resp = api.get(f"/api/v1/movies/{movie.slug}/")
    assert resp.status_code == 200
    assert len(resp.data["seasons"]) == 1
    assert resp.data["seasons"][0]["episodes"][0]["episode_number"] == 1


@pytest.mark.django_db
def test_catalog_hides_video_sources(api):
    """XAVFSIZLIK: bunny_video_id / embed kodlari API'da OCHILMAYDI (P2-T4 gating)."""
    movie = _movie("Secret", bunny_video_id="bunny-xyz", film_embed_code="<iframe>")
    s1 = Season.objects.create(movie=movie, number=1)
    Episode.objects.create(
        movie=movie, season=s1, title="Ep1", episode_number=1, bunny_video_id="ep-bunny-123"
    )
    resp = api.get(f"/api/v1/movies/{movie.slug}/")
    body = str(resp.data)
    assert "bunny-xyz" not in body
    assert "ep-bunny-123" not in body
    assert "bunny_video_id" not in resp.data
    ep = resp.data["seasons"][0]["episodes"][0]
    assert "bunny_video_id" not in ep
    assert "video_embed_code" not in ep


@pytest.mark.django_db
def test_filter_by_genre(api):
    g = Genre.objects.create(name="Drama", slug="drama")
    m1 = _movie("WithGenre")
    m1.genres.add(g)
    _movie("NoGenre")
    resp = api.get("/api/v1/movies/?genre=drama")
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["title"] == "WithGenre"


@pytest.mark.django_db
def test_filter_by_year(api):
    _movie("Old", year=2010)
    _movie("New", year=2024)
    resp = api.get("/api/v1/movies/?year=2024")
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["title"] == "New"


@pytest.mark.django_db
def test_detail_no_n_plus_one(api, django_assert_max_num_queries):
    movie = _movie("Serial")
    s1 = Season.objects.create(movie=movie, number=1)
    for i in range(1, 6):
        Episode.objects.create(movie=movie, season=s1, title=f"Ep{i}", episode_number=i)
    movie.genres.add(Genre.objects.create(name="Drama", slug="drama"))
    # prefetch tufayli so'rovlar soni episode soniga BOG'LIQ EMAS
    with django_assert_max_num_queries(12):
        resp = api.get(f"/api/v1/movies/{movie.slug}/")
        assert resp.status_code == 200


@pytest.mark.django_db
def test_genres_list(api):
    Genre.objects.create(name="Drama", slug="drama")
    Genre.objects.create(name="Comedy", slug="comedy")
    resp = api.get("/api/v1/genres/")
    assert resp.status_code == 200
    assert resp.data["count"] == 2


# --- P2-T5: search, ordering, throttle ---


@pytest.mark.django_db
def test_search_finds_by_title(api):
    _movie("Qishki Sevgi")
    _movie("Yozgi Hikoya")
    resp = api.get("/api/v1/movies/?search=qish")
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["title"] == "Qishki Sevgi"


@pytest.mark.django_db
def test_ordering_by_year_asc(api):
    _movie("Old", year=2010)
    _movie("New", year=2024)
    resp = api.get("/api/v1/movies/?ordering=year")
    titles = [m["title"] for m in resp.data["results"]]
    assert titles == ["Old", "New"]


@pytest.mark.django_db
def test_ordering_by_rating_desc(api):
    low = _movie("Low")
    high = _movie("High")
    Movie.objects.filter(pk=low.pk).update(average_rating=5)
    Movie.objects.filter(pk=high.pk).update(average_rating=9)
    resp = api.get("/api/v1/movies/?ordering=-average_rating")
    titles = [m["title"] for m in resp.data["results"]]
    assert titles == ["High", "Low"]


@pytest.mark.django_db
def test_genre_search(api):
    Genre.objects.create(name="Drama", slug="drama")
    Genre.objects.create(name="Komediya", slug="komediya")
    resp = api.get("/api/v1/genres/?search=dram")
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_search_throttle_returns_429(api):
    """search scope (30/min) limitidan oshganda 429 qaytadi."""
    from django.core.cache import cache

    cache.clear()  # throttle hisoblagichni reset
    _movie("X")
    statuses = [api.get("/api/v1/movies/?search=x").status_code for _ in range(31)]
    assert 429 in statuses
    cache.clear()  # keyingi testlar uchun tozalash


# --- P2-T4: video playback gating + signed URL ---


@pytest.fixture
def bunny(settings):
    settings.BUNNY_STREAM_CDN_HOSTNAME = "vz-test.b-cdn.net"
    settings.BUNNY_STREAM_LIBRARY_ID = "12345"
    return settings


def _episode(movie, num, **kwargs):
    season, _ = Season.objects.get_or_create(movie=movie, number=1)
    return Episode.objects.create(
        movie=movie, season=season, title=f"E{num}", episode_number=num, **kwargs
    )


@pytest.mark.django_db
def test_playback_free_episode_anon(api, bunny):
    ep = _episode(_movie("Free"), 1, bunny_video_id="vid-1")
    resp = api.get(f"/api/v1/episodes/{ep.id}/playback/")
    assert resp.status_code == 200
    assert "hls_url" in resp.data
    assert resp.data["expires_in"] == 4 * 3600


@pytest.mark.django_db
def test_playback_vip_blocks_anon(api, bunny):
    ep = _episode(_movie("VIP", is_vip=True), 11, bunny_video_id="vid-11")
    resp = api.get(f"/api/v1/episodes/{ep.id}/playback/")
    assert resp.status_code == 403
    assert resp.data["restriction"] == "vip"


@pytest.mark.django_db
def test_playback_vip_allows_premium(api, bunny):
    user = User.objects.create_user(username="prem", password="pass12345")
    user.profile.is_premium = True
    user.profile.premium_until = timezone.now() + timedelta(days=30)
    user.profile.save()
    ep = _episode(_movie("VIP", is_vip=True), 11, bunny_video_id="vid-11")
    api.force_authenticate(user)
    assert api.get(f"/api/v1/episodes/{ep.id}/playback/").status_code == 200


@pytest.mark.django_db
def test_playback_superuser_bypasses(api, bunny):
    su = User.objects.create_superuser(username="admin", password="pass12345")
    ep = _episode(_movie("VIP", is_vip=True), 11, bunny_video_id="vid-11")
    api.force_authenticate(su)
    assert api.get(f"/api/v1/episodes/{ep.id}/playback/").status_code == 200


@pytest.mark.django_db
def test_playback_funding_blocks_non_contributor(api, bunny):
    from funding.models import FundingProject

    movie = _movie("Fund")
    FundingProject.objects.create(movie=movie, target_amount=1000)
    ep = _episode(movie, 11, bunny_video_id="vid-11")
    api.force_authenticate(User.objects.create_user(username="nc", password="pass12345"))
    resp = api.get(f"/api/v1/episodes/{ep.id}/playback/")
    assert resp.status_code == 403
    assert resp.data["restriction"] == "funding"


@pytest.mark.django_db
def test_playback_funding_allows_contributor(api, bunny):
    from funding.models import FundingContributor, FundingProject

    movie = _movie("Fund")
    project = FundingProject.objects.create(movie=movie, target_amount=1000)
    ep = _episode(movie, 11, bunny_video_id="vid-11")
    user = User.objects.create_user(username="contrib", password="pass12345")
    FundingContributor.objects.create(project=project, profile=user.profile, amount_paid=100)
    api.force_authenticate(user)
    assert api.get(f"/api/v1/episodes/{ep.id}/playback/").status_code == 200


@pytest.mark.django_db
def test_playback_no_video_returns_404(api, bunny):
    ep = _episode(_movie("NoVid"), 1)  # bunny_video_id yo'q
    assert api.get(f"/api/v1/episodes/{ep.id}/playback/").status_code == 404


@pytest.mark.django_db
def test_signed_url_includes_token(bunny):
    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    from drama.bunny_stream import signed_hls_url

    url = signed_hls_url("vid-1")
    assert "token=" in url
    assert "expires=" in url


def test_signed_url_unconfigured_is_plain():
    """Token kalitisiz (dev): imzosiz oddiy URL."""
    from drama.bunny_stream import signed_hls_url

    url = signed_hls_url("vid-1")
    assert "token=" not in url
