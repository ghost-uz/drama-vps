"""drama app testlari — P1-T1: rasm optimizatsiyasi (save() -> Celery)."""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from core.images import is_new_upload, optimize_to_webp
from drama.models import Episode, Movie, Season
from drama.tasks import optimize_image_task
from users.models import WatchProgress


def _image_bytes(fmt="JPEG", size=(2000, 2000), color="red"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _uploaded(name="poster.jpg", fmt="JPEG"):
    return SimpleUploadedFile(name, _image_bytes(fmt=fmt), content_type="image/jpeg")


# --- optimize_to_webp (sof PIL, DB'siz) ---


def test_optimize_to_webp_returns_webp():
    content = optimize_to_webp(io.BytesIO(_image_bytes()), max_size=(1280, 1280), quality=80)
    assert content is not None
    data = content.read()
    # WEBP magic: 0-3 "RIFF", 8-11 "WEBP"
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"


def test_optimize_to_webp_shrinks_large_image():
    content = optimize_to_webp(io.BytesIO(_image_bytes(size=(3000, 3000))), (1280, 1280), 80)
    assert content is not None
    out = Image.open(io.BytesIO(content.read()))
    assert max(out.size) <= 1280


def test_optimize_to_webp_invalid_returns_none():
    assert optimize_to_webp(io.BytesIO(b"not an image"), (100, 100), 80) is None


# --- is_new_upload ---


def test_is_new_upload_true_for_fresh_upload():
    movie = Movie(title="Test", poster=_uploaded())
    assert is_new_upload(movie.poster) is True


def test_is_new_upload_false_for_empty():
    assert is_new_upload(Movie(title="Test").poster) is False


# --- optimize_image_task (DB, Celery eager) ---


@pytest.mark.django_db
def test_task_converts_poster_to_webp():
    movie = Movie.objects.create(
        title="Task Test", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    optimize_image_task.apply(args=["drama", "movie", movie.pk, "poster", [1280, 1280], 80])
    movie.refresh_from_db()
    assert movie.poster.name.lower().endswith(".webp")


@pytest.mark.django_db
def test_task_idempotent_skips_webp():
    movie = Movie.objects.create(
        title="Idem", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    optimize_image_task.apply(args=["drama", "movie", movie.pk, "poster", [1280, 1280], 80])
    movie.refresh_from_db()
    first = movie.poster.name
    # Ikkinchi marta — allaqachon .webp, skip qiladi (nom o'zgarmaydi)
    optimize_image_task.apply(args=["drama", "movie", movie.pk, "poster", [1280, 1280], 80])
    movie.refresh_from_db()
    assert movie.poster.name == first


@pytest.mark.django_db
def test_task_missing_object_no_error():
    # O'chirilgan obyekt uchun xato bermasligi kerak
    optimize_image_task.apply(args=["drama", "movie", 999999, "poster", [1280, 1280], 80])


# --- mixin save() on_commit task rejalashtirishi ---


@pytest.mark.django_db
def test_mixin_schedules_task_on_save(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        movie = Movie.objects.create(
            title="Mixin", description="x", country="KR", poster=_uploaded("p.jpg")
        )
    # save() yangi yuklangan poster uchun on_commit task rejalashtirgan
    assert len(callbacks) >= 1
    # eager + execute=True: task bajarilgan, poster .webp bo'lgan
    movie.refresh_from_db()
    assert movie.poster.name.lower().endswith(".webp")


@pytest.mark.django_db
def test_mixin_no_task_without_image(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        Movie.objects.create(title="NoImg", description="x", country="KR")
    # Rasm yo'q — task rejalashtirilmaydi
    assert len(callbacks) == 0


# --- P1-T2: Season modeli ---


@pytest.mark.django_db
def test_season_creation_and_str():
    movie = Movie.objects.create(title="S Test", description="x", country="KR")
    season = Season.objects.create(movie=movie, number=1)
    assert str(season) == f"{movie.title} - 1-fasl"
    named = Season.objects.create(movie=movie, number=2, title="Maxsus")
    assert str(named) == "Maxsus"


@pytest.mark.django_db
def test_episode_linked_to_season():
    movie = Movie.objects.create(title="EP Link", description="x", country="KR")
    season = Season.objects.create(movie=movie, number=1)
    ep = Episode.objects.create(movie=movie, season=season, episode_number=1, title="Ep1")
    assert ep.season == season
    assert season.episodes.count() == 1


@pytest.mark.django_db
def test_season_unique_per_movie():
    from django.db import IntegrityError, transaction

    movie = Movie.objects.create(title="Uniq", description="x", country="KR")
    Season.objects.create(movie=movie, number=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Season.objects.create(movie=movie, number=1)


@pytest.mark.django_db
def test_movie_seasons_reverse():
    movie = Movie.objects.create(title="Rev", description="x", country="KR")
    Season.objects.create(movie=movie, number=1)
    Season.objects.create(movie=movie, number=2)
    assert movie.seasons.count() == 2


@pytest.mark.django_db
def test_data_migration_logic_assigns_season_one():
    # 0018_populate_seasons mantiqi: mavjud (season=None) episode -> "Season 1"
    movie = Movie.objects.create(title="DataMig", description="x", country="KR")
    ep = Episode.objects.create(movie=movie, episode_number=1, title="Ep1")
    assert ep.season is None
    season, _ = Season.objects.get_or_create(movie=movie, number=1)
    Episode.objects.filter(movie=movie, season__isnull=True).update(season=season)
    ep.refresh_from_db()
    assert ep.season == season
    assert ep.season.number == 1


# --- P1-T3: WatchProgress ---


def _movie_episode_user(title="WP", username="wpuser"):
    movie = Movie.objects.create(title=title, description="x", country="KR")
    ep = Episode.objects.create(movie=movie, episode_number=1, title="E1")
    user = User.objects.create_user(username, password="pass12345")
    return movie, ep, user


@pytest.mark.django_db
def test_watch_progress_percent():
    _, ep, user = _movie_episode_user()
    wp = WatchProgress.objects.create(
        user=user, episode=ep, position_seconds=45, duration_seconds=90
    )
    assert wp.percent == 50


@pytest.mark.django_db
def test_watch_progress_unique():
    from django.db import IntegrityError, transaction

    _, ep, user = _movie_episode_user()
    WatchProgress.objects.create(user=user, episode=ep)
    with pytest.raises(IntegrityError), transaction.atomic():
        WatchProgress.objects.create(user=user, episode=ep)


@pytest.mark.django_db
def test_save_progress_endpoint(client):
    _, ep, user = _movie_episode_user(username="ep_user")
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep.id])
    resp = client.post(url, {"position_seconds": 30, "duration_seconds": 100})
    assert resp.status_code == 200
    wp = WatchProgress.objects.get(user=user, episode=ep)
    assert wp.position_seconds == 30
    assert wp.completed is False


@pytest.mark.django_db
def test_save_progress_auto_complete(client):
    _, ep, user = _movie_episode_user(username="ac_user")
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep.id])
    resp = client.post(url, {"position_seconds": 95, "duration_seconds": 100})
    assert resp.status_code == 200
    wp = WatchProgress.objects.get(user=user, episode=ep)
    assert wp.completed is True


@pytest.mark.django_db
def test_save_progress_requires_login(client):
    _, ep, _user = _movie_episode_user(username="anon_owner")
    url = reverse("drama:save_watch_progress", args=[ep.id])
    resp = client.post(url, {"position_seconds": 10, "duration_seconds": 100})
    assert resp.status_code == 302  # login sahifasiga redirect
