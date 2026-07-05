"""drama/api/ katalog API testlari [P2-T2]."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from drama.factories import EpisodeFactory, MovieFactory
from drama.models import Episode, Genre, Movie, Season

# `api` va `bunny` fixture'lar endi loyiha-darajali conftest.py da [P11-T1]


def _movie(title, **kwargs):
    return MovieFactory(title=title, **kwargs)


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


def _episode(movie, num, **kwargs):
    return EpisodeFactory(movie=movie, episode_number=num, **kwargs)


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


# --- P4-T1: to'liq imzolangan URL qamrovi (token_path, IP, embed, HTML view) ---


def test_hls_url_signed_with_token_path(bunny):
    """Papka (token_path) imzolanadi — HLS segmentlari ham shu token bilan o'tadi."""
    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    from drama.bunny_stream import hls_url

    url = hls_url("vid-1")
    assert url.startswith("https://vz-test.b-cdn.net/vid-1/playlist.m3u8?")
    assert "token=" in url
    assert "token_path=%2Fvid-1%2F" in url
    assert "expires=" in url


def test_hls_token_matches_reference_algorithm(bunny, monkeypatch):
    """Imzo Bunny rasmiy formulasi bilan bit-ma-bit mos (regressiya qulfi)."""
    import base64
    import hashlib
    import time

    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    bunny.BUNNY_TOKEN_EXPIRY_SECONDS = 4 * 3600
    monkeypatch.setattr(time, "time", lambda: 1_750_000_000)
    from drama.bunny_stream import hls_url

    url = hls_url("vid-1")
    expires = 1_750_000_000 + 4 * 3600
    hashable = f"secret-key/vid-1/{expires}token_path=/vid-1/"
    expected = (
        base64.b64encode(hashlib.sha256(hashable.encode()).digest())
        .decode()
        .replace("+", "-")
        .replace("/", "_")
        .replace("=", "")
    )
    assert f"token={expected}" in url
    assert f"expires={expires}" in url


def test_get_all_urls_every_url_signed(bunny):
    """HTML pleyer ishlatadigan BARCHA URL'lar (hls/mp4/thumb/preview/embed) imzoli."""
    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    from drama.bunny_stream import get_all_urls

    urls = get_all_urls("vid-1")
    assert urls
    assert all("token=" in u for u in urls.values())


def test_ip_binding_changes_token(bunny, monkeypatch):
    """user_ip imzoga kiradi — boshqa IP'dan olingan token ishlamaydi."""
    import time

    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    monkeypatch.setattr(time, "time", lambda: 1_750_000_000)
    from drama.bunny_stream import hls_url

    assert hls_url("vid-1", user_ip="1.2.3.4") != hls_url("vid-1")


def test_token_user_ip_only_when_enabled(bunny, rf):
    """IP bog'lash default O'CHIQ (proxy/IPv6 nomuvofiqligi videoni sindirmasin)."""
    from drama.bunny_stream import token_user_ip

    request = rf.get("/", HTTP_CF_CONNECTING_IP="7.7.7.7")
    assert token_user_ip(request) == ""
    bunny.BUNNY_TOKEN_BIND_IP = True
    assert token_user_ip(request) == "7.7.7.7"


def test_embed_url_uses_hex_token(bunny, monkeypatch):
    """Embed pleyer boshqa format kutadi: SHA256_HEX(key + video_id + expires)."""
    import hashlib
    import time

    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    bunny.BUNNY_TOKEN_EXPIRY_SECONDS = 4 * 3600
    monkeypatch.setattr(time, "time", lambda: 1_750_000_000)
    from drama.bunny_stream import embed_url

    expires = 1_750_000_000 + 4 * 3600
    expected = hashlib.sha256(f"secret-keyvid-1{expires}".encode()).hexdigest()
    assert embed_url("vid-1") == (
        f"https://iframe.mediadelivery.net/embed/12345/vid-1?token={expected}&expires={expires}"
    )


@pytest.mark.django_db
def test_movie_detail_html_player_signed(client, bunny):
    """HTML pleyer konteksti imzolangan URL oladi — asosiy ochiq-URL sizishi yopildi."""
    bunny.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    movie = _movie("Signed Serial")
    _episode(movie, 1, bunny_video_id="vid-9")
    resp = client.get(f"/{movie.slug}/")
    assert resp.status_code == 200
    assert "token=" in resp.context["video_hls"]
    assert "token_path=%2Fvid-9%2F" in resp.context["video_hls"]
    assert "token=" in resp.context["video_720"]
    assert "token=" in resp.context["video_thumbnail"]


# --- P11-T3: pagination + playback throttle gap-fill ---


@pytest.mark.django_db
def test_movie_list_pagination(api):
    """PAGE_SIZE=20: 25 kino -> 1-sahifa 20 + next, 2-sahifa 5 + next=None."""
    for i in range(25):
        _movie(f"Paginate {i}")
    resp = api.get("/api/v1/movies/")
    assert resp.data["count"] == 25
    assert len(resp.data["results"]) == 20
    assert resp.data["next"]
    resp2 = api.get("/api/v1/movies/?page=2")
    assert len(resp2.data["results"]) == 5
    assert resp2.data["next"] is None


@pytest.mark.django_db
def test_playback_throttle_429(api, bunny):
    """Playback scope 60/daqiqa: 61-chi so'rovda 429 (signed-URL farm himoyasi)."""
    from django.core.cache import cache

    cache.clear()
    ep = _episode(_movie("Throttle Play"), 1, bunny_video_id="vid-thr")
    statuses = [api.get(f"/api/v1/episodes/{ep.id}/playback/").status_code for _ in range(61)]
    assert 429 in statuses
    cache.clear()
