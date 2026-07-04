"""users/api/ va Review API testlari [P2-T3]."""

import pytest

from drama.factories import MovieFactory
from drama.models import Episode, Review, Season
from users.factories import UserFactory
from users.models import UserMovieList, WatchProgress

# `api` fixture endi loyiha-darajali conftest.py da [P11-T1]


def _user(username="u1"):
    return UserFactory(username=username)


def _movie(title="M"):
    return MovieFactory(title=title)


# --- Profil (me) ---


@pytest.mark.django_db
def test_me_requires_auth(api):
    assert api.get("/api/v1/me/").status_code == 401


@pytest.mark.django_db
def test_me_returns_profile(api):
    api.force_authenticate(_user())
    resp = api.get("/api/v1/me/")
    assert resp.status_code == 200
    assert resp.data["username"] == "u1"


@pytest.mark.django_db
def test_me_update_bio(api):
    user = _user()
    api.force_authenticate(user)
    resp = api.patch("/api/v1/me/", {"bio": "yangi bio"})
    assert resp.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.bio == "yangi bio"


@pytest.mark.django_db
def test_me_cannot_change_balance(api):
    """XAVFSIZLIK: balance API orqali o'zgartirilmaydi (read-only)."""
    user = _user()
    user.profile.balance = 100
    user.profile.save()
    api.force_authenticate(user)
    resp = api.patch("/api/v1/me/", {"balance": 999999})
    assert resp.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.balance == 100


# --- Watchlist (IDOR izolyatsiya) ---


@pytest.mark.django_db
def test_watchlist_create_and_list(api):
    user = _user()
    movie = _movie()
    api.force_authenticate(user)
    resp = api.post("/api/v1/watchlist/", {"movie": movie.id, "status": 1})
    assert resp.status_code == 201
    assert api.get("/api/v1/watchlist/").data["count"] == 1


@pytest.mark.django_db
def test_watchlist_isolation(api):
    """IDOR: foydalanuvchi faqat o'z ro'yxatini ko'radi."""
    u1, u2 = _user("u1"), _user("u2")
    UserMovieList.objects.create(profile=u1.profile, movie=_movie(), status=1)
    api.force_authenticate(u2)
    assert api.get("/api/v1/watchlist/").data["count"] == 0


# --- WatchProgress upsert ---


@pytest.mark.django_db
def test_watch_progress_upsert_and_complete(api):
    user = _user()
    movie = _movie()
    s1 = Season.objects.create(movie=movie, number=1)
    ep = Episode.objects.create(movie=movie, season=s1, title="E1", episode_number=1)
    api.force_authenticate(user)
    r1 = api.post(
        "/api/v1/watch-progress/",
        {"episode": ep.id, "position_seconds": 50, "duration_seconds": 100},
    )
    assert r1.status_code == 201
    # Upsert: ikkinchi POST yangi yozuv yaratmaydi, yangilaydi
    r2 = api.post(
        "/api/v1/watch-progress/",
        {"episode": ep.id, "position_seconds": 95, "duration_seconds": 100},
    )
    assert r2.status_code == 200
    assert WatchProgress.objects.filter(user=user, episode=ep).count() == 1
    assert WatchProgress.objects.get(user=user, episode=ep).completed is True


# --- Review ---


@pytest.mark.django_db
def test_review_create_requires_auth(api):
    movie = _movie()
    assert api.post("/api/v1/reviews/", {"movie": movie.id, "text": "zo'r"}).status_code == 401


@pytest.mark.django_db
def test_review_create_sets_user_server_side(api):
    user = _user()
    movie = _movie()
    api.force_authenticate(user)
    resp = api.post("/api/v1/reviews/", {"movie": movie.id, "text": "zo'r film"})
    assert resp.status_code == 201
    assert Review.objects.get(id=resp.data["id"]).user == user


@pytest.mark.django_db
def test_review_list_public(api):
    movie = _movie()
    Review.objects.create(user=_user(), movie=movie, text="izoh")
    resp = api.get(f"/api/v1/reviews/?movie={movie.slug}")
    assert resp.status_code == 200
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_review_delete_owner_or_admin_only(api):
    owner, other = _user("owner"), _user("other")
    review = Review.objects.create(user=owner, movie=_movie(), text="izoh")
    api.force_authenticate(other)
    assert api.delete(f"/api/v1/reviews/{review.id}/").status_code == 403
    api.force_authenticate(owner)
    assert api.delete(f"/api/v1/reviews/{review.id}/").status_code == 204
