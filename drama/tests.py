"""drama app testlari — P1-T1: rasm optimizatsiyasi (save() -> Celery)."""

import io
import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.images import is_new_upload, optimize_to_webp
from drama.models import Episode, Movie, Season
from drama.tasks import (
    optimize_image_task,
    process_episode_upload,
    publish_scheduled_movies,
    recompute_movie_rating,
)
from users.models import UserMovieList, WatchProgress


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


# --- P1-T5: reyting birlashtirish (recompute_movie_rating + signal) ---


def _rate(username, movie, score, status=2):
    """User + UserMovieList yozuvi (score string yoki None)."""
    user = User.objects.create_user(username=username, password="pass12345")
    UserMovieList.objects.create(profile=user.profile, movie=movie, status=status, score=score)
    return user


@pytest.mark.django_db
def test_recompute_sets_average_and_votes():
    movie = Movie.objects.create(
        title="Rate A", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    _rate("ra1", movie, "8.0")
    _rate("ra2", movie, "6.0")
    _rate("ra3", movie, "10.0")
    recompute_movie_rating(movie.id)
    movie.refresh_from_db()
    assert movie.total_votes == 3
    assert movie.average_rating == 8  # (8+6+10)/3


@pytest.mark.django_db
def test_recompute_ignores_null_scores():
    movie = Movie.objects.create(
        title="Rate B", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    _rate("rb1", movie, "7.0")
    _rate("rb2", movie, None, status=3)  # "rejada", bahosiz
    recompute_movie_rating(movie.id)
    movie.refresh_from_db()
    assert movie.total_votes == 1
    assert movie.average_rating == 7


@pytest.mark.django_db
def test_recompute_no_scores_resets_to_zero():
    movie = Movie.objects.create(
        title="Rate C", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    Movie.objects.filter(pk=movie.id).update(average_rating=5, total_votes=3)
    recompute_movie_rating(movie.id)
    movie.refresh_from_db()
    assert movie.total_votes == 0
    assert movie.average_rating == 0


@pytest.mark.django_db
def test_average_rating_stores_ten_after_fix():
    """max_digits=4 bug fix: 10.00 baho saqlanadi (avval 3 → overflow edi)."""
    movie = Movie.objects.create(
        title="Rate D", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    _rate("rd1", movie, "10.0")
    recompute_movie_rating(movie.id)
    movie.refresh_from_db()
    assert movie.average_rating == 10
    assert movie.total_votes == 1


@pytest.mark.django_db
def test_score_change_triggers_recompute_signal(django_capture_on_commit_callbacks):
    movie = Movie.objects.create(
        title="Rate E", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    user = User.objects.create_user(username="re1", password="pass12345")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        UserMovieList.objects.create(profile=user.profile, movie=movie, status=2, score="9.0")
    assert len(callbacks) >= 1
    movie.refresh_from_db()
    assert movie.total_votes == 1
    assert movie.average_rating == 9


@pytest.mark.django_db
def test_backfill_migration_seeds_ratings():
    import importlib

    from django.apps import apps as global_apps

    movie = Movie.objects.create(
        title="Rate F", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    _rate("rf1", movie, "8.0")
    Movie.objects.filter(pk=movie.id).update(average_rating=0, total_votes=0)
    mig = importlib.import_module("drama.migrations.0020_backfill_movie_ratings")
    mig.backfill_movie_ratings(global_apps, None)
    movie.refresh_from_db()
    assert movie.total_votes == 1
    assert movie.average_rating == 8


# --- P1-T6: publish workflow (status/publish_at + manager + beat task) ---


def _movie(title, status=Movie.Status.PUBLISHED, publish_at=None):
    return Movie.objects.create(
        title=title,
        description="x",
        country="KR",
        poster=_uploaded("p.jpg"),
        status=status,
        publish_at=publish_at,
    )


@pytest.mark.django_db
def test_published_includes_published_excludes_draft():
    pub = _movie("Pub", status=Movie.Status.PUBLISHED)
    draft = _movie("Draft", status=Movie.Status.DRAFT)
    ids = set(Movie.objects.published().values_list("id", flat=True))
    assert pub.id in ids
    assert draft.id not in ids


@pytest.mark.django_db
def test_published_excludes_future_scheduled():
    future = _movie(
        "Future",
        status=Movie.Status.SCHEDULED,
        publish_at=timezone.now() + timedelta(hours=1),
    )
    ids = set(Movie.objects.published().values_list("id", flat=True))
    assert future.id not in ids


@pytest.mark.django_db
def test_published_includes_past_scheduled_self_healing():
    """Self-healing: beat o'tkazmagan bo'lsa ham, vaqti yetgan scheduled public ko'rinadi."""
    past = _movie(
        "Past",
        status=Movie.Status.SCHEDULED,
        publish_at=timezone.now() - timedelta(minutes=1),
    )
    ids = set(Movie.objects.published().values_list("id", flat=True))
    assert past.id in ids


@pytest.mark.django_db
def test_due_for_publish_only_past_scheduled():
    past = _movie(
        "P", status=Movie.Status.SCHEDULED, publish_at=timezone.now() - timedelta(minutes=1)
    )
    future = _movie(
        "F", status=Movie.Status.SCHEDULED, publish_at=timezone.now() + timedelta(hours=1)
    )
    pub = _movie("Pub", status=Movie.Status.PUBLISHED)
    due_ids = set(Movie.objects.due_for_publish().values_list("id", flat=True))
    assert due_ids == {past.id}
    assert future.id not in due_ids
    assert pub.id not in due_ids


@pytest.mark.django_db
def test_publish_scheduled_movies_task_promotes_only_due():
    past = _movie(
        "P", status=Movie.Status.SCHEDULED, publish_at=timezone.now() - timedelta(minutes=1)
    )
    future = _movie(
        "F", status=Movie.Status.SCHEDULED, publish_at=timezone.now() + timedelta(hours=1)
    )
    count = publish_scheduled_movies()
    assert count == 1
    past.refresh_from_db()
    future.refresh_from_db()
    assert past.status == Movie.Status.PUBLISHED
    assert future.status == Movie.Status.SCHEDULED  # kelajak tegilmaydi


@pytest.mark.django_db
def test_scheduled_without_publish_at_violates_constraint():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Movie.objects.create(
            title="Bad",
            description="x",
            country="KR",
            poster=_uploaded("p.jpg"),
            status=Movie.Status.SCHEDULED,
            publish_at=None,
        )


@pytest.mark.django_db
def test_scheduled_with_publish_at_allowed():
    m = _movie(
        "Good", status=Movie.Status.SCHEDULED, publish_at=timezone.now() + timedelta(hours=2)
    )
    assert m.pk is not None


def test_clean_rejects_scheduled_without_publish_at():
    movie = Movie(title="x", status=Movie.Status.SCHEDULED, publish_at=None)
    with pytest.raises(ValidationError):
        movie.clean()


def test_clean_allows_draft_without_publish_at():
    Movie(title="x", status=Movie.Status.DRAFT, publish_at=None).clean()  # xato ko'tarmaydi


# --- P3-T1: Bunny upload pipeline ---


def _episode_with_video(title="UpMovie"):
    movie = Movie.objects.create(
        title=title, description="x", country="KR", poster=_uploaded("p.jpg")
    )
    season = Season.objects.create(movie=movie, number=1)
    return Episode.objects.create(
        movie=movie,
        season=season,
        title="E1",
        episode_number=1,
        video_file=SimpleUploadedFile("v.mp4", b"video-bytes"),
    )


@pytest.mark.django_db
def test_episode_upload_success(monkeypatch):
    from unittest.mock import MagicMock

    from drama.services import bunny_upload

    ep = _episode_with_video("UpOk")
    monkeypatch.setattr(bunny_upload, "create_video", lambda title: "guid-123")
    monkeypatch.setattr(bunny_upload, "upload_video", MagicMock())
    monkeypatch.setattr(bunny_upload, "get_status", lambda guid: 4)  # Finished
    process_episode_upload(ep.id)
    ep.refresh_from_db()
    assert ep.bunny_video_id == "guid-123"
    assert ep.upload_status == Episode.UploadStatus.READY
    assert not ep.video_file  # vaqtinchalik fayl tozalandi


@pytest.mark.django_db
def test_episode_upload_failed(monkeypatch):
    from unittest.mock import MagicMock

    from drama.services import bunny_upload

    ep = _episode_with_video("UpErr")
    monkeypatch.setattr(bunny_upload, "create_video", lambda title: "guid-err")
    monkeypatch.setattr(bunny_upload, "upload_video", MagicMock())
    monkeypatch.setattr(bunny_upload, "get_status", lambda guid: 5)  # Error
    process_episode_upload(ep.id)
    ep.refresh_from_db()
    assert ep.upload_status == Episode.UploadStatus.FAILED


@pytest.mark.django_db
def test_episode_save_triggers_upload_task(django_capture_on_commit_callbacks, monkeypatch):
    from unittest.mock import MagicMock

    movie = Movie.objects.create(
        title="Trig", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    season = Season.objects.create(movie=movie, number=1)
    task_mock = MagicMock()
    monkeypatch.setattr("drama.tasks.process_episode_upload.delay", task_mock)
    with django_capture_on_commit_callbacks(execute=True):
        Episode.objects.create(
            movie=movie,
            season=season,
            title="E1",
            episode_number=1,
            video_file=SimpleUploadedFile("v.mp4", b"video-bytes"),
        )
    task_mock.assert_called_once()


# --- P3-T2: Bunny webhook handler ---


def _ep_for_webhook(guid, num=1):
    movie = Movie.objects.create(
        title=f"W{guid}", description="x", country="KR", poster=_uploaded("p.jpg")
    )
    season = Season.objects.create(movie=movie, number=1)
    return Episode.objects.create(
        movie=movie,
        season=season,
        title="E1",
        episode_number=num,
        bunny_video_id=guid,
        upload_status="processing",
    )


@pytest.mark.django_db
def test_bunny_webhook_finished_sets_ready(client, settings):
    settings.BUNNY_WEBHOOK_SECRET = "test-secret"
    ep = _ep_for_webhook("guid-ok")
    resp = client.post(
        "/webhooks/bunny/?secret=test-secret",
        data=json.dumps({"VideoGuid": "guid-ok", "Status": 4}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    ep.refresh_from_db()
    assert ep.upload_status == Episode.UploadStatus.READY


@pytest.mark.django_db
def test_bunny_webhook_error_sets_failed(client, settings):
    settings.BUNNY_WEBHOOK_SECRET = "test-secret"
    ep = _ep_for_webhook("guid-err")
    resp = client.post(
        "/webhooks/bunny/?secret=test-secret",
        data=json.dumps({"VideoGuid": "guid-err", "Status": 5}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    ep.refresh_from_db()
    assert ep.upload_status == Episode.UploadStatus.FAILED


@pytest.mark.django_db
def test_bunny_webhook_wrong_secret_403(client, settings):
    settings.BUNNY_WEBHOOK_SECRET = "test-secret"
    resp = client.post(
        "/webhooks/bunny/?secret=WRONG",
        data=json.dumps({"VideoGuid": "g", "Status": 4}),
        content_type="application/json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_bunny_webhook_no_secret_403(client, settings):
    settings.BUNNY_WEBHOOK_SECRET = "test-secret"
    resp = client.post(
        "/webhooks/bunny/",
        data=json.dumps({"VideoGuid": "g", "Status": 4}),
        content_type="application/json",
    )
    assert resp.status_code == 403
