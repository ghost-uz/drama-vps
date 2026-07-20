"""drama app testlari — P1-T1: rasm optimizatsiyasi (save() -> Celery)."""

import io
import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.images import is_new_upload, optimize_to_webp
from drama.models import Episode, Movie, Review, Season, Tag, TopSlider, UploadStatus
from drama.tasks import (
    optimize_image_task,
    process_episode_upload,
    process_video_upload,
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
    # Rasm yo'q — optimize task rejalashtirilmaydi. Movie save har doim 2 ta
    # on_commit callback beradi: [P9-T1] trending-recompute + [P8-T1] FTS vektor.
    reprs = repr(callbacks)
    assert len(callbacks) == 2
    assert "recompute_trending_tags" in reprs
    assert "update_search_vector" in reprs
    assert "optimize_image_task" not in reprs


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


# --- Smart continue: qism tugatilgach keyingisi 'davom ettirish' navbatiga tushadi ---


@pytest.mark.django_db
def test_completed_episode_queues_next(client):
    movie, ep1, user = _movie_episode_user(username="next_user")
    ep2 = Episode.objects.create(movie=movie, episode_number=2, title="E2")
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep1.id])
    client.post(url, {"position_seconds": 95, "duration_seconds": 100})  # 90%+ -> completed
    queued = WatchProgress.objects.get(user=user, episode=ep2)
    assert queued.completed is False and queued.position_seconds == 0
    # 'Davom ettirish'da endi shu serialdan FAQAT ep2 chiqadi
    from users.selectors import continue_watching

    assert [wp.episode_id for wp in continue_watching(user)] == [ep2.id]


@pytest.mark.django_db
def test_queue_next_skips_already_completed_episode(client):
    movie, ep1, user = _movie_episode_user(username="skip_user")
    ep2 = Episode.objects.create(movie=movie, episode_number=2, title="E2")
    ep3 = Episode.objects.create(movie=movie, episode_number=3, title="E3")
    # ep2 allaqachon to'liq ko'rilgan (rewatch stsenariysi) -> navbatga ep3 tushadi
    WatchProgress.objects.create(
        user=user, episode=ep2, position_seconds=100, duration_seconds=100, completed=True
    )
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep1.id])
    client.post(url, {"position_seconds": 95, "duration_seconds": 100})
    assert WatchProgress.objects.filter(user=user, episode=ep3, completed=False).exists()


@pytest.mark.django_db
def test_queue_next_does_not_overwrite_partial_next(client):
    movie, ep1, user = _movie_episode_user(username="keep_user")
    ep2 = Episode.objects.create(movie=movie, episode_number=2, title="E2")
    WatchProgress.objects.create(user=user, episode=ep2, position_seconds=40, duration_seconds=100)
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep1.id])
    client.post(url, {"position_seconds": 95, "duration_seconds": 100})
    # get_or_create — ep2'ning chala progressi USTIGA YOZILMAGAN
    assert WatchProgress.objects.get(user=user, episode=ep2).position_seconds == 40


@pytest.mark.django_db
def test_queue_next_noop_when_no_next_episode(client):
    _movie, ep, user = _movie_episode_user(username="last_user")
    client.force_login(user)
    url = reverse("drama:save_watch_progress", args=[ep.id])
    client.post(url, {"position_seconds": 95, "duration_seconds": 100})
    # Serial oxiri: yangi qator ochilmaydi, ro'yxat ham bo'sh (completed chiqmaydi)
    assert WatchProgress.objects.filter(user=user).count() == 1


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
    # Episode.save endi generik process_video_upload'ni navbatga qo'yadi [P14-T1]
    monkeypatch.setattr("drama.tasks.process_video_upload.delay", task_mock)
    with django_capture_on_commit_callbacks(execute=True):
        ep = Episode.objects.create(
            movie=movie,
            season=season,
            title="E1",
            episode_number=1,
            video_file=SimpleUploadedFile("v.mp4", b"video-bytes"),
        )
    task_mock.assert_called_once_with("drama", "episode", ep.pk)


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


# --- P4-T2: check_bunny_security buyrug'i (CDN mock bilan) ---


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_cdn(responses):
    """(imzoli?, yot-referer?, referer-bor?) holatiga qarab status qaytaradi."""

    def fake_get(url, headers=None, timeout=None, stream=None):
        referer = (headers or {}).get("Referer", "")
        key = ("token=" in url, "evil" in referer, bool(referer))
        return _FakeResponse(responses[key])

    return fake_get


# Holatlar: (imzoli, yot referer, referer bor) -> status
_SECURE_CDN = {
    (False, False, False): 403,  # imzosiz -> rad
    (True, False, True): 200,  # imzoli + to'g'ri referer -> OK
    (True, True, True): 403,  # imzoli + yot referer -> rad (hotlink)
    (True, False, False): 200,  # imzoli, referersiz -> OK (mobil)
}


def _run_check(monkeypatch, settings, responses, *args):
    settings.BUNNY_STREAM_CDN_HOSTNAME = "vz-test.b-cdn.net"
    settings.BUNNY_STREAM_LIBRARY_ID = "12345"
    settings.BUNNY_STREAM_TOKEN_KEY = "secret-key"
    from drama.management.commands import check_bunny_security as cmd

    monkeypatch.setattr(cmd.requests, "get", _fake_cdn(responses))
    out = io.StringIO()
    call_command("check_bunny_security", "vid-1", *args, stdout=out)
    return out.getvalue()


def test_check_bunny_security_all_clean(monkeypatch, settings):
    out = _run_check(monkeypatch, settings, _SECURE_CDN)
    assert "Barcha tekshiruvlar toza" in out


def test_check_bunny_security_detects_token_auth_off(monkeypatch, settings):
    """Imzosiz URL 200 = panelda token auth yoqilmagan — aniqlanishi shart."""
    responses = {**_SECURE_CDN, (False, False, False): 200}
    out = _run_check(monkeypatch, settings, responses)
    assert "CDN token authentication" in out
    with pytest.raises(CommandError):
        _run_check(monkeypatch, settings, responses, "--strict")


def test_check_bunny_security_detects_open_referer(monkeypatch, settings):
    """Yot referer 200 = hotlink ochiq — aniqlanishi shart."""
    responses = {**_SECURE_CDN, (True, True, True): 200}
    out = _run_check(monkeypatch, settings, responses)
    assert "Allowed Referrers" in out


def test_check_bunny_security_warns_no_referrer_blocked(monkeypatch, settings):
    """Referersiz 403 — muammo EMAS, lekin mobil-pleyer ogohlantirishi chiqadi."""
    responses = {**_SECURE_CDN, (True, False, False): 403}
    out = _run_check(monkeypatch, settings, responses)
    assert "Block no-referrer" in out
    assert "Barcha tekshiruvlar toza" in out  # warning muammo hisoblanmaydi


# --- P5-T4: SEO structured data (JSON-LD, canonical, hreflang) ---


def _jsonld_blocks(html):
    """Sahifadagi barcha ld+json bloklarini PARSE qiladi — sintaksis buzuq bo'lsa fail."""
    import re

    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert blocks, "ld+json blok topilmadi"
    return [json.loads(b) for b in blocks]


@pytest.mark.django_db
def test_movie_detail_jsonld_rich_and_quote_safe(client):
    """Qo'shtirnoqli sarlavha JSONni buzmaydi (eski qo'lda-shablon xavfi) + to'liq graf."""
    from drama.factories import EpisodeFactory, GenreFactory, MovieFactory

    movie = MovieFactory(title='Drama "Alpha" seriali', year=2024)
    movie.genres.add(GenreFactory())
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid-1")
    html = client.get(movie.get_absolute_url()).content.decode()
    graph = next(p for p in _jsonld_blocks(html) if "@graph" in p)["@graph"]
    types = {item["@type"] for item in graph}
    assert {"TVSeries", "TVEpisode", "VideoObject", "BreadcrumbList"} <= types
    series = next(i for i in graph if i["@type"] == "TVSeries")
    assert series["name"] == movie.title  # &quot; emas — asl qo'shtirnoq qaytadi
    video = next(i for i in graph if i["@type"] == "VideoObject")
    assert video["uploadDate"] and video["thumbnailUrl"] and video["embedUrl"]


@pytest.mark.django_db
def test_film_without_episodes_is_movie_type(client):
    """Epizodsiz yakka film: Movie tipi + video Movie'ning o'zidan."""
    from drama.factories import MovieFactory

    movie = MovieFactory(bunny_video_id="film-1")
    html = client.get(movie.get_absolute_url()).content.decode()
    graph = next(p for p in _jsonld_blocks(html) if "@graph" in p)["@graph"]
    types = {item["@type"] for item in graph}
    assert "Movie" in types
    assert "TVEpisode" not in types
    assert "VideoObject" in types


@pytest.mark.django_db
def test_head_canonical_and_hreflang(client):
    from drama.factories import EpisodeFactory, MovieFactory

    movie = MovieFactory()
    EpisodeFactory(movie=movie, episode_number=1)
    html = client.get(movie.get_absolute_url()).content.decode()
    assert f'rel="canonical" href="http://testserver{movie.get_absolute_url()}"' in html
    assert 'hreflang="uz"' in html
    assert 'hreflang="x-default"' in html
    assert 'hreflang="en"' not in html  # en URL'lar yo'q — chiqmasligi SHART


@pytest.mark.django_db
def test_genre_page_unique_title(client):
    """Ro'yxat sahifalari view'dagi `title` kontekstidan unikal <title> oladi."""
    from drama.factories import GenreFactory, MovieFactory

    genre = GenreFactory(name="Romantika", slug="romantika")
    MovieFactory().genres.add(genre)
    html = client.get(f"/janr/{genre.slug}/").content.decode()
    assert "<title>Romantika janridagi kinolar - Drama.uz</title>" in html


# --- P5-T2: pleyer (player.js, resume, avto-keyingi, API refresh) ---


def _reels_data(html):
    import re

    m = re.search(r'<script id="reelsData" type="application/json">(.*?)</script>', html, re.S)
    assert m, "reelsData topilmadi"
    return json.loads(m.group(1))


@pytest.mark.django_db
def test_movie_detail_uses_external_player(client):
    """Inline pleyer static/js/player.js ga ko'chirilgan; hls.js vendorlangan."""
    from drama.factories import EpisodeFactory, MovieFactory

    movie = MovieFactory()
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid-1")
    html = client.get(movie.get_absolute_url()).content.decode()
    assert "js/player.js" in html
    assert "js/vendor/hls.min.js" in html
    assert "cdn.jsdelivr.net/npm/hls.js" not in html
    assert "SWIPE NAVIGATION" not in html  # inline blok chiqarilgan


@pytest.mark.django_db
def test_reels_data_player_fields_anonymous(client):
    from drama.factories import EpisodeFactory, MovieFactory

    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid-1")
    data = _reels_data(client.get(movie.get_absolute_url()).content.decode())
    assert data["episodeId"] == ep.id
    assert data["resumePos"] == 0  # anonimda resume yo'q
    assert data["playbackApi"] == f"/api/v1/episodes/{ep.id}/playback/"
    assert data["progressUrl"].endswith(f"episode/{ep.id}/progress/")


@pytest.mark.django_db
def test_resume_position_for_authenticated(client):
    from drama.factories import EpisodeFactory, MovieFactory
    from users.factories import UserFactory

    user = UserFactory()
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid-1")
    WatchProgress.objects.create(user=user, episode=ep, position_seconds=120, duration_seconds=600)
    client.force_login(user)
    data = _reels_data(client.get(movie.get_absolute_url()).content.decode())
    assert data["resumePos"] == 120


@pytest.mark.django_db
def test_completed_episode_not_resumed(client):
    """Ko'rib tugatilgan qism boshidan boshlanadi (resume 0)."""
    from drama.factories import EpisodeFactory, MovieFactory
    from users.factories import UserFactory

    user = UserFactory()
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid-1")
    WatchProgress.objects.create(
        user=user, episode=ep, position_seconds=590, duration_seconds=600, completed=True
    )
    client.force_login(user)
    data = _reels_data(client.get(movie.get_absolute_url()).content.decode())
    assert data["resumePos"] == 0


def test_player_static_assets_exist():
    from django.contrib.staticfiles import finders

    assert finders.find("js/player.js")
    assert finders.find("js/vendor/hls.min.js")


# --- P10-T2: rate limiting (web) ---


@pytest.mark.django_db
def test_live_search_rate_limited_429(client):
    """Jonli qidiruv limitdan keyin 429 JSON (API search scope bilan bir xil tezlik)."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("drama:live_search")
    for _ in range(30):  # settings.RATELIMIT_RATES["live_search"] = 30/m
        client.get(url, {"q": "dr"})
    resp = client.get(url, {"q": "dr"})
    assert resp.status_code == 429
    assert resp.json()["detail"]
    cache.clear()


# --- P11-T2: gating service unit testlari (to'g'ridan, API qatlamisiz) ---


@pytest.mark.django_db
def test_gating_free_limit_boundary():
    """10-qism tekin chegara, 11-qism VIP'da yopiq (FREE_EPISODE_LIMIT invarianti)."""
    from django.contrib.auth.models import AnonymousUser

    from drama.factories import EpisodeFactory, MovieFactory
    from drama.services.playback import FREE_EPISODE_LIMIT, get_episode_access

    movie = MovieFactory(is_vip=True)
    ep10 = EpisodeFactory(movie=movie, episode_number=FREE_EPISODE_LIMIT)
    ep11 = EpisodeFactory(movie=movie, episode_number=FREE_EPISODE_LIMIT + 1)
    anon = AnonymousUser()
    assert get_episode_access(anon, ep10) == (True, None)
    assert get_episode_access(anon, ep11) == (False, "vip")


@pytest.mark.django_db
def test_gating_plain_11plus_is_free():
    """11+ lekin VIP ham, funding ham emas -> tekin (hujjatlangan qoida)."""
    from django.contrib.auth.models import AnonymousUser

    from drama.factories import EpisodeFactory, MovieFactory
    from drama.services.playback import get_episode_access

    ep = EpisodeFactory(movie=MovieFactory(is_vip=False), episode_number=25)
    assert get_episode_access(AnonymousUser(), ep) == (True, None)


@pytest.mark.django_db
def test_gating_expired_premium_blocked():
    """Muddati o'tgan premium VIP qismni OCHMAYDI (is_currently_premium=False)."""
    from datetime import timedelta

    from django.utils import timezone

    from drama.factories import EpisodeFactory, MovieFactory
    from drama.services.playback import get_episode_access
    from users.factories import UserFactory

    user = UserFactory()
    user.profile.is_premium = True
    user.profile.premium_until = timezone.now() - timedelta(days=1)
    user.profile.save()
    ep = EpisodeFactory(movie=MovieFactory(is_vip=True), episode_number=11)
    assert get_episode_access(user, ep) == (False, "vip")


@pytest.mark.django_db
def test_gating_funding_takes_precedence_over_vip():
    """Funding loyihali kino: VIP premium ham YORDAM BERMAYDI — faqat hissa ochadi."""
    from datetime import timedelta

    from django.utils import timezone

    from drama.factories import EpisodeFactory, MovieFactory
    from drama.services.playback import get_episode_access
    from funding.factories import FundingContributorFactory, FundingProjectFactory
    from users.factories import UserFactory

    movie = MovieFactory(is_vip=True)
    project = FundingProjectFactory(movie=movie)
    ep = EpisodeFactory(movie=movie, episode_number=11)

    premium_user = UserFactory()
    premium_user.profile.is_premium = True
    premium_user.profile.premium_until = timezone.now() + timedelta(days=30)
    premium_user.profile.save()
    assert get_episode_access(premium_user, ep) == (False, "funding")

    FundingContributorFactory(project=project, profile=premium_user.profile)
    assert get_episode_access(premium_user, ep) == (True, None)


# --- P5-T5: video/image sitemap + poster karta varianti (srcset) ---


@pytest.mark.django_db
def test_sitemap_includes_image_namespace(client):
    from drama.factories import MovieFactory

    movie = MovieFactory()
    xml = client.get("/sitemap.xml").content.decode()
    assert 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' in xml
    assert "<image:loc>" in xml
    assert movie.get_absolute_url() in xml


@pytest.mark.django_db
def test_video_sitemap_only_movies_with_video(client):
    from drama.factories import EpisodeFactory, MovieFactory

    with_video = MovieFactory(title="Videoli Serial")
    EpisodeFactory(movie=with_video, episode_number=1)
    MovieFactory(title="Videosiz Kino")  # epizodsiz va bunny'siz — kirmasligi kerak
    xml = client.get("/sitemap-video.xml").content.decode()
    assert "<video:video>" in xml
    assert with_video.get_absolute_url() in xml
    assert "Videoli Serial" in xml
    assert "Videosiz Kino" not in xml


@pytest.mark.django_db
def test_robots_lists_both_sitemaps(client):
    body = client.get("/robots.txt").content.decode()
    assert "/sitemap.xml" in body
    assert "/sitemap-video.xml" in body


@pytest.mark.django_db
def test_poster_card_variant_created(django_capture_on_commit_callbacks):
    """Yangi poster: task asosiy webp + 342px karta variantini yaratadi [P5-T5]."""
    with django_capture_on_commit_callbacks(execute=True):
        movie = Movie.objects.create(
            title="Card Variant Test",
            description="d",
            country="KR",
            poster=SimpleUploadedFile("p.jpg", _image_bytes(), content_type="image/jpeg"),
        )
    movie.refresh_from_db()
    assert movie.poster.name.lower().endswith(".webp")
    assert movie.poster_card.name.lower().endswith("_card.webp")


@pytest.mark.django_db
def test_optimize_command_backfills_missing_card():
    """Asosiy allaqachon webp, karta bo'sh (eski ma'lumot) — --sync to'ldiradi."""
    movie = Movie.objects.create(
        title="Backfill Card",
        description="d",
        country="KR",
        poster=SimpleUploadedFile("p.webp", _image_bytes(fmt="WEBP"), content_type="image/webp"),
    )
    movie.refresh_from_db()
    assert not movie.poster_card  # on_commit testda bajarilmagan — karta bo'sh
    call_command("optimize_images", "--sync")
    movie.refresh_from_db()
    assert movie.poster_card.name.lower().endswith("_card.webp")


# --- P14-T1: Movie video pipeline + admin Bunny UI ---


def _movie_with_video(title="FilmUp"):
    return Movie.objects.create(
        title=title,
        description="x",
        country="KR",
        poster=_uploaded("p.jpg"),
        video_file=SimpleUploadedFile("film.mp4", b"video-bytes"),
    )


def _admin_client(client, name="boss"):
    user = User.objects.create_superuser(name, f"{name}@drama.uz", "pass12345")
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_movie_save_with_video_triggers_upload(django_capture_on_commit_callbacks, monkeypatch):
    """Yakka film: video_file yuklansa status UPLOADING + generik task navbatda."""
    from unittest.mock import MagicMock

    task_mock = MagicMock()
    monkeypatch.setattr("drama.tasks.process_video_upload.delay", task_mock)
    with django_capture_on_commit_callbacks(execute=True):
        movie = _movie_with_video("TrigFilm")
    assert movie.upload_status == UploadStatus.UPLOADING
    task_mock.assert_called_once_with("drama", "movie", movie.pk)


@pytest.mark.django_db
def test_movie_upload_success(monkeypatch):
    """Movie ham Episode bilan bir xil pipeline'dan o'tadi: GUID + READY + fayl tozalanadi."""
    from unittest.mock import MagicMock

    from drama.services import bunny_upload

    movie = _movie_with_video("FilmOk")
    monkeypatch.setattr(bunny_upload, "create_video", lambda title: "guid-film")
    monkeypatch.setattr(bunny_upload, "upload_video", MagicMock())
    monkeypatch.setattr(bunny_upload, "get_status", lambda guid: 4)  # Finished
    process_video_upload("drama", "movie", movie.id)
    movie.refresh_from_db()
    assert movie.bunny_video_id == "guid-film"
    assert movie.upload_status == UploadStatus.READY
    assert not movie.video_file


@pytest.mark.django_db
def test_bunny_webhook_updates_movie(client, settings):
    """Webhook endi GUID'ni Movie'da ham qidiradi (yakka film encoding tayyor)."""
    settings.BUNNY_WEBHOOK_SECRET = "sec"
    movie = _movie_with_video("HookFilm")
    Movie.objects.filter(pk=movie.pk).update(
        bunny_video_id="guid-hook-film", upload_status=UploadStatus.PROCESSING
    )
    resp = client.post(
        "/webhooks/bunny/?secret=sec",
        json.dumps({"VideoGuid": "guid-hook-film", "Status": 4}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    movie.refresh_from_db()
    assert movie.upload_status == UploadStatus.READY


@pytest.mark.django_db
def test_admin_retry_action_requeues_failed(client, monkeypatch):
    """FAILED qism: GUID tozalanadi, status UPLOADING, task qayta navbatda."""
    from unittest.mock import MagicMock

    _admin_client(client)
    ep = _episode_with_video("RetryUp")
    Episode.objects.filter(pk=ep.pk).update(
        upload_status=UploadStatus.FAILED, bunny_video_id="guid-old"
    )
    task_mock = MagicMock()
    monkeypatch.setattr("drama.tasks.process_video_upload.delay", task_mock)
    resp = client.post(
        reverse("admin:drama_episode_changelist"),
        {"action": "retry_bunny_upload", "_selected_action": [ep.pk]},
    )
    assert resp.status_code == 302
    ep.refresh_from_db()
    assert ep.upload_status == UploadStatus.UPLOADING
    assert ep.bunny_video_id == ""
    task_mock.assert_called_once_with("drama", "episode", ep.pk)


@pytest.mark.django_db
def test_admin_retry_action_skips_without_file(client, monkeypatch):
    """Lokal fayl o'chirilgan (READY) qism qayta yuklanmaydi — GUID saqlanadi."""
    from unittest.mock import MagicMock

    _admin_client(client, "boss2")
    ep = _episode_with_video("NoFile")
    Episode.objects.filter(pk=ep.pk).update(
        video_file="", upload_status=UploadStatus.READY, bunny_video_id="guid-keep"
    )
    task_mock = MagicMock()
    monkeypatch.setattr("drama.tasks.process_video_upload.delay", task_mock)
    client.post(
        reverse("admin:drama_episode_changelist"),
        {"action": "retry_bunny_upload", "_selected_action": [ep.pk]},
    )
    ep.refresh_from_db()
    assert ep.bunny_video_id == "guid-keep"
    assert ep.upload_status == UploadStatus.READY
    task_mock.assert_not_called()


@pytest.mark.django_db
def test_admin_refresh_action_polls_stuck_processing(client, monkeypatch):
    """Tiqilib qolgan PROCESSING (webhook o'tkazib yuborilgan): poll qayta uyg'onadi."""
    from unittest.mock import MagicMock

    _admin_client(client, "boss3")
    ep = _episode_with_video("Stuck")
    Episode.objects.filter(pk=ep.pk).update(
        upload_status=UploadStatus.PROCESSING, bunny_video_id="guid-stuck"
    )
    task_mock = MagicMock()
    monkeypatch.setattr("drama.tasks.process_video_upload.delay", task_mock)
    client.post(
        reverse("admin:drama_episode_changelist"),
        {"action": "refresh_bunny_status", "_selected_action": [ep.pk]},
    )
    task_mock.assert_called_once_with("drama", "episode", ep.pk)
    ep.refresh_from_db()
    assert ep.bunny_video_id == "guid-stuck"  # refresh GUID'ga tegmaydi


@pytest.mark.django_db
def test_admin_episode_changelist_renders(client):
    """EpisodeAdmin ro'yxati (badge/filter konfiguratsiyasi) ochiladi."""
    _admin_client(client, "boss4")
    _episode_with_video("ListEp")
    resp = client.get(reverse("admin:drama_episode_changelist"))
    assert resp.status_code == 200


# --- P9-T1: katalog keshi — versiyalangan kalitlar + invalidatsiya ---


@pytest.mark.django_db
def test_catalog_key_changes_on_bump():
    from django.core.cache import cache

    from drama.cache import bump_catalog_version, catalog_key

    cache.clear()
    key_before = catalog_key("years")
    bump_catalog_version()
    key_after = catalog_key("years")
    assert key_before != key_after
    assert key_after.startswith("catalog:v")


@pytest.mark.django_db
def test_movie_save_bumps_catalog_version():
    from django.core.cache import cache

    from drama.cache import catalog_version

    cache.clear()
    before = catalog_version()
    Movie.objects.create(title="BumpKino", description="x", country="KR", poster=_uploaded())
    assert catalog_version() > before


@pytest.mark.django_db
def test_tags_m2m_change_bumps_catalog_version():
    """movie.tags.add post_save chaqirmaydi — m2m_changed signal qamraydi."""
    from django.core.cache import cache

    from drama.cache import catalog_version

    movie = Movie.objects.create(title="M2mKino", description="x", country="KR", poster=_uploaded())
    tag = Tag.objects.create(name="Sirli", slug="sirli-m2m")
    cache.clear()
    before = catalog_version()
    movie.tags.add(tag)
    assert catalog_version() > before


@pytest.mark.django_db
def test_explore_filters_update_immediately_on_new_movie(client):
    """Acceptance: kontent o'zgarsa filtr ro'yxatlari DARHOL yangilanadi.

    Yangi yilli kino qo'shilishi bump orqali ham data-kesh, ham fragment-kesh
    kalitini almashtiradi — 86400s TTL kutilmaydi.
    """
    from django.core.cache import cache

    cache.clear()
    Movie.objects.create(
        title="Eski Yil Kino", description="x", country="KR", year=2001, poster=_uploaded()
    )
    resp1 = client.get(reverse("drama:explore"))
    assert b"2001" in resp1.content
    assert b"2031" not in resp1.content

    Movie.objects.create(
        title="Yangi Yil Kino", description="x", country="KR", year=2031, poster=_uploaded()
    )
    resp2 = client.get(reverse("drama:explore"))
    assert b"2031" in resp2.content


@pytest.mark.django_db
def test_home_slider_fragment_invalidated_on_slider_save(client):
    """Slayder fragment-keshi catalog_ver kalitli — yangi slayder darhol chiqadi."""
    from django.core.cache import cache

    cache.clear()
    TopSlider.objects.create(name="Slayder Birinchi", rank="1", image=_uploaded("s1.jpg"))
    resp1 = client.get("/")
    assert b"Slayder Birinchi" in resp1.content

    TopSlider.objects.create(name="Slayder Ikkinchi", rank="2", image=_uploaded("s2.jpg"))
    resp2 = client.get("/")
    assert b"Slayder Ikkinchi" in resp2.content


@pytest.mark.django_db
def test_similar_movies_cached_and_refreshed(client):
    """similar ID'lar versiyalangan keshda; yangi mos kino bump'dan keyin chiqadi."""
    from django.core.cache import cache

    cache.clear()
    tag = Tag.objects.create(name="Tarixiy", slug="tarixiy-sim")
    main = Movie.objects.create(
        title="Bosh Kino Sim", description="x", country="KR", poster=_uploaded()
    )
    other = Movie.objects.create(
        title="Oxshash Kino Bir", description="x", country="KR", poster=_uploaded()
    )
    main.tags.add(tag)
    other.tags.add(tag)

    # similar_movies endi episodeSheet'da render qilinadi [P8-T2]; bu yerda
    # kesh semantikasi (bump'da qayta hisoblash) view kontekstida tekshiriladi.
    resp1 = client.get(main.get_absolute_url())
    assert [m.title for m in resp1.context["similar_movies"]] == ["Oxshash Kino Bir"]

    third = Movie.objects.create(
        title="Oxshash Kino Ikki", description="x", country="KR", poster=_uploaded()
    )
    third.tags.add(tag)  # m2m bump -> keyingi so'rovda similar qayta hisoblanadi
    resp2 = client.get(main.get_absolute_url())
    titles = {m.title for m in resp2.context["similar_movies"]}
    assert titles == {"Oxshash Kino Bir", "Oxshash Kino Ikki"}


@pytest.mark.django_db
def test_publish_task_bumps_catalog_version():
    """publish_scheduled_movies bulk .update() ishlatadi — qo'lda bump majburiy."""
    from django.core.cache import cache

    from drama.cache import catalog_version

    Movie.objects.create(
        title="Rejalangan Kino",
        description="x",
        country="KR",
        poster=_uploaded(),
        status=Movie.Status.SCHEDULED,
        publish_at=timezone.now() - timedelta(minutes=1),
    )
    cache.clear()
    before = catalog_version()
    assert publish_scheduled_movies() == 1
    assert catalog_version() > before
    # Hech narsa chop etilmasa versiya tegilmaydi
    stable = catalog_version()
    assert publish_scheduled_movies() == 0
    assert catalog_version() == stable


@pytest.mark.django_db
def test_webhook_ready_bumps_catalog_version(client, settings):
    from django.core.cache import cache

    from drama.cache import catalog_version

    settings.BUNNY_WEBHOOK_SECRET = "sec"
    ep = _episode_with_video("HookBump")
    Episode.objects.filter(pk=ep.pk).update(bunny_video_id="guid-bump", upload_status="processing")
    cache.clear()
    before = catalog_version()
    resp = client.post(
        "/webhooks/bunny/?secret=sec",
        json.dumps({"VideoGuid": "guid-bump", "Status": 4}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert catalog_version() > before


@pytest.mark.django_db
def test_personalization_stays_live_with_caches(client):
    """Acceptance: login foydalanuvchi kontenti keshga aralashmaydi.

    Sahifa to'liq keshlanmaydi — faqat global bo'laklar; shaxsiy karusel
    (continue_watching) har request'da jonli hisoblanadi.
    """
    from django.core.cache import cache

    from users.models import WatchProgress

    cache.clear()
    # Anonim tashrif fragment/data keshlarni isitadi
    anon = client.get("/")
    assert anon.status_code == 200
    assert "continue_watching" not in anon.context

    user = User.objects.create_user(username="kesh_user", password="pass12345")
    ep = _episode_with_video("KeshSerial")
    WatchProgress.objects.create(user=user, episode=ep, position_seconds=42, duration_seconds=100)
    client.force_login(user)
    auth = client.get("/")
    progresses = list(auth.context["continue_watching"])
    assert len(progresses) == 1 and progresses[0].position_seconds == 42


# --- P9-T2: DB so'rov auditi — N+1 yo'q, so'rov soni doimiy ---


def _movie_with_episodes(title, ep_count=2, year=2024):
    movie = Movie.objects.create(
        title=title, description="x", country="KR", year=year, poster=_uploaded()
    )
    season = Season.objects.create(movie=movie, number=1)
    for n in range(1, ep_count + 1):
        Episode.objects.create(movie=movie, season=season, title=f"E{n}", episode_number=n)
    return movie


@pytest.mark.django_db
def test_index_query_count_constant(client, django_assert_num_queries):
    """Bosh sahifa: 8 karta x 2 epizod — so'rovlar soni kartaga bog'liq EMAS.

    Oldin har karta `episodes.count` uchun 3 tagacha COUNT so'rovi berardi;
    endi with_card_data() annotatsiyasi bilan: paginator COUNT + kartalar
    SELECT + trenddagi karusel _cards SELECT = 3 (kesh issiq; trending ID'lar
    keshda, obyektlar har request'da bitta SELECT bilan olinadi) [P8-T2].
    """
    from django.core.cache import cache

    cache.clear()
    for i in range(8):
        _movie_with_episodes(f"Idx Kino {i}")
    client.get("/")  # katalog data + fragment + trending ID keshlarini isitadi
    with django_assert_num_queries(3):
        resp = client.get("/")
    assert resp.status_code == 200
    assert b"Idx Kino 7" in resp.content
    assert b"2-qism" in resp.content  # annotatsiya kartada ishlayapti


@pytest.mark.django_db
def test_explore_query_count_constant(client, django_assert_num_queries):
    from django.core.cache import cache

    cache.clear()
    for i in range(6):
        _movie_with_episodes(f"Exp Kino {i}")
    client.get(reverse("drama:explore"))
    with django_assert_num_queries(2):
        resp = client.get(reverse("drama:explore"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_detail_query_count_constant_as_content_grows(client, django_assert_num_queries):
    """Detail: reviewlar (avatar/javoblari bilan) ko'paysa ham so'rov soni O'ZGARMAYDI.

    Kutilgan (issiq kesh, anonim): 1 movie(+category+funding join) +
    prefetchlar (episodes/genres/main_actors/tags/reviews/replies) + 1
    similar pk-fetch + 1 subtitles [V2E-T1] = 9. Oldin har review profile
    (avatar) va replies uchun alohida so'rov ochardi.
    """
    from django.core.cache import cache

    movie = _movie_with_episodes("Detail Kino", ep_count=3)
    author = User.objects.create_user(username="sharh_user", password="pass12345")
    admin_u = User.objects.create_superuser("sharh_admin", "a@d.uz", "pass12345")
    for i in range(2):
        r = Review.objects.create(user=author, movie=movie, text=f"Fikr {i}")
        Review.objects.create(user=admin_u, movie=movie, text=f"Javob {i}", parent=r)

    cache.clear()
    url = movie.get_absolute_url()
    client.get(url)  # kesh isitish (catalog + similar ID'lar)
    with django_assert_num_queries(9):
        client.get(url)

    # Kontent o'sadi: +3 review (har biri javobli). Review katalog modeli EMAS
    # -> kesh versiyasi o'zgarmaydi, so'rovlar soni ham o'sha-o'sha qolsin.
    for i in range(3):
        r = Review.objects.create(user=author, movie=movie, text=f"Yangi fikr {i}")
        Review.objects.create(user=admin_u, movie=movie, text=f"Yangi javob {i}", parent=r)
    with django_assert_num_queries(9):
        resp = client.get(url)
    assert b"Yangi fikr 2" in resp.content


@pytest.mark.django_db
def test_movie_reviews_page_no_comment_n_plus_one(client, django_assert_num_queries):
    """Fikrlar sahifasi: 10 review + javoblar — so'rov soni doimiy."""
    from django.core.cache import cache

    movie = _movie_with_episodes("Fikrlar Kino", ep_count=1)
    author = User.objects.create_user(username="fikr_user", password="pass12345")
    admin_u = User.objects.create_superuser("fikr_admin", "f@d.uz", "pass12345")
    for i in range(10):
        r = Review.objects.create(user=author, movie=movie, text=f"Fikr {i}")
        if i % 2 == 0:
            Review.objects.create(user=admin_u, movie=movie, text=f"Javob {i}", parent=r)

    cache.clear()
    url = reverse("drama:movie_reviews", kwargs={"slug": movie.slug})
    client.get(url)
    # 1 movie lookup + paginator COUNT + reviews SELECT + replies prefetch = 4
    with django_assert_num_queries(4):
        resp = client.get(url)
    assert resp.status_code == 200


# --- P8-T1: qidiruv servisi (sqlite FALLBACK yo'li; FTS testlari postgres_tests.py da) ---


@pytest.mark.django_db
def test_search_fallback_finds_title_and_original():
    """sqlite'da servis icontains fallback bilan title/original_title dan topadi."""
    from drama.factories import MovieFactory
    from drama.services.search import search_movies

    hit_title = MovieFactory(title="Qora Sarv")
    hit_orig = MovieFactory(title="Boshqa nom", original_title="Sarv Story")
    MovieFactory(title="Aloqasiz film")

    res = list(search_movies(Movie.objects.published(), "sarv"))
    assert {m.pk for m in res} == {hit_title.pk, hit_orig.pk}


@pytest.mark.django_db
def test_search_short_or_empty_query_returns_none():
    """<2 belgi — bo'sh natija (live-search dropdown qoidasi bilan bir xil)."""
    from drama.factories import MovieFactory
    from drama.services.search import search_movies

    MovieFactory(title="A Film")
    assert list(search_movies(Movie.objects.published(), "a")) == []
    assert list(search_movies(Movie.objects.published(), "")) == []
    assert list(search_movies(Movie.objects.published(), None)) == []


# --- P8-T2: tavsiyalar (o'xshash / trenddagi / siz ko'rganingiz asosida) ---


def _watch(user, episode, **kwargs):
    from users.models import WatchProgress

    return WatchProgress.objects.create(user=user, episode=episode, **kwargs)


@pytest.mark.django_db
def test_compute_trending_ranks_by_recent_views():
    """Trenddagi: oxirgi hafta ko'rish faolligi ko'p kino oldinda."""
    from drama import recommendations
    from drama.factories import EpisodeFactory, MovieFactory

    hot = MovieFactory(title="Qaynoq")
    cold = MovieFactory(title="Sovuq")
    hot_ep = EpisodeFactory(movie=hot)
    cold_ep = EpisodeFactory(movie=cold)
    u1 = User.objects.create_user("t_u1", password="pass12345")
    u2 = User.objects.create_user("t_u2", password="pass12345")
    _watch(u1, hot_ep)
    _watch(u2, hot_ep)
    _watch(u1, cold_ep)

    ids = recommendations.compute_trending_ids(limit=12)
    assert ids.index(hot.id) < ids.index(cold.id)


@pytest.mark.django_db
def test_compute_trending_fills_when_no_activity():
    """Faollik yo'q bo'lsa ham bo'sh chiqmaydi — baho/ovoz bo'yicha to'ldiriladi."""
    from drama import recommendations
    from drama.factories import MovieFactory

    MovieFactory(average_rating=9)
    MovieFactory(average_rating=5)
    ids = recommendations.compute_trending_ids(limit=12)
    assert len(ids) == 2  # ko'rishlar yo'q, lekin ikkala kino ham to'ldirishda


@pytest.mark.django_db
def test_recompute_trending_movies_task_caches_ids():
    """Beat task ID'larni versiyalangan keshga yozadi; trending_movies o'qiydi."""
    from django.core.cache import cache

    from drama import recommendations
    from drama.cache import catalog_key
    from drama.factories import MovieFactory
    from drama.tasks import recompute_trending_movies

    cache.clear()
    movie = MovieFactory()
    n = recompute_trending_movies(limit=12)
    assert n == 1
    assert cache.get(catalog_key(recommendations.TRENDING_CACHE_KEY)) == [movie.id]
    assert [m.id for m in recommendations.trending_movies()] == [movie.id]


@pytest.mark.django_db
def test_similar_uses_tags_and_genres():
    """O'xshash: janr mosligi ham hisobga olinadi (eski faqat-teg mantiqidan yaxshi)."""
    from drama import recommendations
    from drama.factories import GenreFactory, MovieFactory, TagFactory

    tag = TagFactory()
    genre = GenreFactory()
    main = MovieFactory(title="Asosiy")
    main.tags.add(tag)
    main.genres.add(genre)

    by_tag = MovieFactory(title="Teg mos")
    by_tag.tags.add(tag)
    by_genre = MovieFactory(title="Janr mos")
    by_genre.genres.add(genre)
    MovieFactory(title="Aloqasiz")

    ids = recommendations.compute_similar_ids(main, limit=6)
    assert {by_tag.id, by_genre.id} <= set(ids)
    assert main.id not in ids


@pytest.mark.django_db
def test_similar_fallback_by_country_when_no_tags_or_genres():
    """Teg/janr yo'q kino — o'sha davlatdagi reyting bilan to'ldiriladi (bo'sh emas)."""
    from drama import recommendations
    from drama.factories import MovieFactory

    main = MovieFactory(country="KR")
    same = MovieFactory(country="KR", mdl_rank=9)
    MovieFactory(country="JP")  # boshqa davlat — chiqmaydi

    ids = recommendations.compute_similar_ids(main, limit=6)
    assert same.id in ids


@pytest.mark.django_db
def test_because_you_watched_recommends_by_genre_excluding_watched():
    """Ko'rilgan kino janridagi HALI KO'RILMAGAN kinolar tavsiya qilinadi."""
    from drama import recommendations
    from drama.factories import EpisodeFactory, GenreFactory, MovieFactory

    genre = GenreFactory()
    watched = MovieFactory(title="Ko'rilgan")
    watched.genres.add(genre)
    ep = EpisodeFactory(movie=watched)
    rec = MovieFactory(title="Tavsiya")
    rec.genres.add(genre)
    MovieFactory(title="Boshqa janr")  # janr mos emas

    user = User.objects.create_user("byw_u", password="pass12345")
    _watch(user, ep)

    result = recommendations.because_you_watched(user, limit=12)
    ids = [m.id for m in result]
    assert rec.id in ids
    assert watched.id not in ids  # ko'rilgan qayta tavsiya qilinmaydi


@pytest.mark.django_db
def test_because_you_watched_anonymous_is_empty():
    """Anonim/tarixsiz foydalanuvchi — bo'sh (shaxsiy tavsiya yo'q)."""
    from django.contrib.auth.models import AnonymousUser

    from drama import recommendations

    assert recommendations.because_you_watched(AnonymousUser()) == []


@pytest.mark.django_db
def test_home_page_renders_recommendation_blocks(client):
    """Acceptance: bosh sahifada trend + davom ettirish + tavsiya bloklari."""
    from django.core.cache import cache

    from drama.factories import EpisodeFactory, GenreFactory, MovieFactory

    cache.clear()
    genre = GenreFactory()
    watched = MovieFactory(title="TarixKino")
    watched.genres.add(genre)
    ep = EpisodeFactory(movie=watched)
    rec = MovieFactory(title="TavsiyaKino")
    rec.genres.add(genre)

    user = User.objects.create_user("home_u", password="pass12345")
    _watch(user, ep, position_seconds=30, duration_seconds=100)
    client.force_login(user)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "trending_movies" in resp.context
    # Davom ettirish (tugatilmagan) + tavsiya (janr mos, ko'rilmagan) render bo'ladi
    assert list(resp.context["continue_watching"])
    assert rec.id in [m.id for m in resp.context["recommended_movies"]]
    body = resp.content.decode()
    assert "Davom ettirish" in body
    assert "Trenddagi" in body


@pytest.mark.django_db
def test_detail_page_renders_similar_section(client):
    """Acceptance: detail sahifada 'o'xshash dramalar' bo'limi ko'rinadi."""
    from django.core.cache import cache

    from drama.factories import GenreFactory, MovieFactory

    cache.clear()
    genre = GenreFactory()
    main = _movie_with_episodes("AsosiySimilar")
    main.genres.add(genre)
    similar = MovieFactory(title="OxshashSimilar")
    similar.genres.add(genre)

    resp = client.get(main.get_absolute_url())
    assert resp.status_code == 200
    assert [m.id for m in resp.context["similar_movies"]] == [similar.id]
    body = resp.content.decode()
    assert "O'xshash dramalar" in body
    assert "OxshashSimilar" in body


# --- P8-T3: faceted filtr sonlari + saralash ---


@pytest.mark.django_db
def test_facets_count_published_movies():
    """Facet sonlari chop etilgan kinolarni sanaydi (janr/davlat/yil)."""
    from django.core.cache import cache

    from drama import facets
    from drama.factories import GenreFactory, MovieFactory

    cache.clear()
    action = GenreFactory(name="Jangari", slug="jangari-f")
    MovieFactory(country="KR", year=2024).genres.add(action)
    MovieFactory(country="KR", year=2024).genres.add(action)
    MovieFactory(country="JP", year=2023)

    genre_map = {g["genres__slug"]: g["count"] for g in facets.genre_facets()}
    assert genre_map["jangari-f"] == 2
    country_map = {c["country"]: c["count"] for c in facets.country_facets()}
    assert country_map["KR"] == 2 and country_map["JP"] == 1
    year_map = {y["year"]: y["count"] for y in facets.year_facets()}
    assert year_map[2024] == 2 and year_map[2023] == 1


@pytest.mark.django_db
def test_explore_sort_by_rating(client):
    """?sort=rating -> mdl_rank kamayish tartibida."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    low = MovieFactory(title="Past", mdl_rank=5)
    high = MovieFactory(title="Baland", mdl_rank=9)
    resp = client.get(reverse("drama:explore"), {"sort": "rating"})
    ids = [m.id for m in resp.context["movies"]]
    assert ids.index(high.id) < ids.index(low.id)
    cache.clear()


@pytest.mark.django_db
def test_explore_sort_by_popular(client):
    """?sort=popular -> total_votes kamayish tartibida."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    quiet = MovieFactory(title="Jim", total_votes=3)
    loud = MovieFactory(title="Mashhur", total_votes=99)
    resp = client.get(reverse("drama:explore"), {"sort": "popular"})
    ids = [m.id for m in resp.context["movies"]]
    assert ids.index(loud.id) < ids.index(quiet.id)
    cache.clear()


@pytest.mark.django_db
def test_explore_invalid_sort_falls_back(client):
    """Yaroqsiz sort qiymati -> default (new), 500 EMAS (injection himoyasi)."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory()
    resp = client.get(reverse("drama:explore"), {"sort": "'; DROP TABLE"})
    assert resp.status_code == 200
    assert resp.context["current_sort"] == "new"
    cache.clear()


@pytest.mark.django_db
def test_explore_renders_facet_counts_and_selection(client):
    """Facet sonlari render bo'ladi; tanlangan janr checkbox checked qoladi."""
    from django.core.cache import cache

    from drama.factories import GenreFactory, MovieFactory

    cache.clear()
    genre = GenreFactory(name="Melodrama", slug="melo-f")
    MovieFactory().genres.add(genre)
    resp = client.get(reverse("drama:explore"), {"genre": "melo-f"})
    body = resp.content.decode()
    assert "Melodrama" in body
    # tanlangan janr checkbox 'checked' bilan render bo'ladi (holat saqlanadi)
    assert 'value="melo-f" class="hidden peer" checked' in body
    assert resp.context["selected_genres"] == ["melo-f"]
    cache.clear()


# =========================================================================
# P5-T3: Cheksiz skroll (HTMX infinite scroll) + progressive enhancement
# =========================================================================


@pytest.mark.django_db
def test_explore_hx_request_returns_partial(client):
    """HX-so'rov -> _movie_items.html partial'i (base.html'siz), kartalar bilan."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory(title="HX Kino")
    resp = client.get(reverse("drama:explore"), headers={"HX-Request": "true"})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "HX Kino" in body
    # Partial base.html'ni O'RAMAYDI (to'liq sahifa emas)
    assert "<html" not in body.lower()
    assert "<!doctype" not in body.lower()
    cache.clear()


@pytest.mark.django_db
def test_explore_sentinel_present_when_more_pages(client):
    """13 kino (>12 paginate_by) -> 1-sahifada 'load-more' sentineli page=2 ga."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory.create_batch(13)
    resp = client.get(reverse("drama:explore"))
    body = resp.content.decode()
    assert 'id="load-more"' in body
    assert "page=2" in body
    cache.clear()


@pytest.mark.django_db
def test_explore_no_sentinel_on_single_page(client):
    """Kam kino (<12) -> keyingi sahifa yo'q -> sentinel render bo'lmaydi."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory.create_batch(3)
    resp = client.get(reverse("drama:explore"))
    assert 'id="load-more"' not in resp.content.decode()
    cache.clear()


@pytest.mark.django_db
def test_infinite_scroll_next_page_appends_cards_and_new_sentinel(client):
    """HX ?page=2 -> kartalar + keyingi (page=3) sentinel; base.html'siz."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory.create_batch(25)  # 3 sahifa (12+12+1)
    resp = client.get(reverse("drama:explore"), {"page": "2"}, headers={"HX-Request": "true"})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "<html" not in body.lower()
    assert 'id="load-more"' in body
    assert "page=3" in body  # sentinel keyingi sahifaga surildi
    cache.clear()


@pytest.mark.django_db
def test_sentinel_preserves_active_filters(client):
    """Filtrlangan katalogda sentinel joriy filtrni (genre) + page ni saqlaydi."""
    from django.core.cache import cache

    from drama.factories import GenreFactory, MovieFactory

    cache.clear()
    genre = GenreFactory(slug="drama-g")
    for _ in range(13):
        MovieFactory().genres.add(genre)
    resp = client.get(reverse("drama:explore"), {"genre": "drama-g"})
    body = resp.content.decode()
    assert 'id="load-more"' in body
    # {% querystring %} joriy GET'ni saqlaydi -> sentinel URL'da genre ham, page ham bor
    assert "genre=drama-g" in body
    assert "page=2" in body
    cache.clear()


@pytest.mark.django_db
def test_sentinel_has_progressive_href(client):
    """Sentinel oddiy <a href="/explore/?page=2"> — JS-siz progressive enhancement."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory.create_batch(13)
    resp = client.get(reverse("drama:explore"))
    body = resp.content.decode()
    # htmx bo'lmasa ham ishlaydigan haqiqiy havola (hx-get YONIDA)
    assert 'href="/explore/?page=2"' in body
    cache.clear()


@pytest.mark.django_db
def test_index_infinite_scroll_sentinel_and_partial(client):
    """Bosh sahifa: to'liq render sentinel bilan; HX -> partial (base.html'siz)."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory.create_batch(13)
    full = client.get(reverse("drama:movie_list"))
    assert 'id="load-more"' in full.content.decode()

    part = client.get(reverse("drama:movie_list"), headers={"HX-Request": "true"})
    body = part.content.decode()
    assert "<html" not in body.lower()  # partial: slayder/karusel yo'q
    assert 'id="load-more"' in body
    cache.clear()


@pytest.mark.django_db
def test_genre_page_infinite_scroll(client):
    """Janr sahifasi (movie_list.html endi yagona kartada): HX -> partial + sentinel."""
    from django.core.cache import cache

    from drama.factories import GenreFactory, MovieFactory

    cache.clear()
    genre = GenreFactory(slug="thriller-g")
    for _ in range(13):
        MovieFactory().genres.add(genre)
    url = reverse("drama:genre_detail", kwargs={"slug": "thriller-g"})
    resp = client.get(url, headers={"HX-Request": "true"})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "<html" not in body.lower()
    assert 'id="load-more"' in body
    cache.clear()


@pytest.mark.django_db
def test_explore_filter_has_noscript_progressive_fallback(client):
    """JS-siz: explore filtri <noscript> submit + method=get bilan ishlaydi."""
    from django.core.cache import cache

    from drama.factories import MovieFactory

    cache.clear()
    MovieFactory()
    resp = client.get(reverse("drama:explore"))
    body = resp.content.decode()
    assert "<noscript>" in body
    assert 'method="get"' in body
    assert "Filtrlarni qo'llash" in body
    cache.clear()


# --- V2B-T1: foydalanuvchilararo izoh javoblari ---


def _reply_fixtures(title="ReplyKino"):
    """Kino + root-izoh muallifi + javob yozuvchi (throttle chelagi toza)."""
    from django.core.cache import cache

    cache.clear()  # locmem testlar orasida yashaydi — review-throttle bleed bo'lmasin
    movie = Movie.objects.create(title=title, description="x", country="KR")
    author = User.objects.create_user("izoh_author", password="pass12345")
    replier = User.objects.create_user("izoh_replier", password="pass12345")
    return movie, author, replier


@pytest.mark.django_db
def test_user_can_reply_to_root_comment(client):
    """Oddiy user reply yoza oladi (403 YO'Q) va HX-javobda badge/ism bor."""
    movie, author, replier = _reply_fixtures()
    root = Review.objects.create(user=author, movie=movie, text="Root fikr")
    client.force_login(replier)
    resp = client.post(
        reverse("drama:add_review", args=[movie.id]),
        {"text": "Qo'shilaman!", "parent": root.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    reply = Review.objects.get(text="Qo'shilaman!")
    assert reply.parent_id == root.id and reply.user == replier
    html = resp.content.decode()
    assert "javob berdi" in html and "izoh_replier" in html


@pytest.mark.django_db
def test_reply_to_reply_attaches_to_thread_root(client):
    """Chuqurlik 1: reply'ga reply -> o'sha threadning ROOT'iga bog'lanadi."""
    movie, author, replier = _reply_fixtures()
    root = Review.objects.create(user=author, movie=movie, text="Root")
    mid = Review.objects.create(user=author, movie=movie, text="Reply1", parent=root)
    client.force_login(replier)
    client.post(reverse("drama:add_review", args=[movie.id]), {"text": "Reply2", "parent": mid.id})
    assert Review.objects.get(text="Reply2").parent_id == root.id


@pytest.mark.django_db
def test_reply_notifies_root_author_but_not_self(client):
    from users.models import Notification

    movie, author, replier = _reply_fixtures()
    root = Review.objects.create(user=author, movie=movie, text="Root")
    client.force_login(replier)
    client.post(reverse("drama:add_review", args=[movie.id]), {"text": "Javob", "parent": root.id})
    n = Notification.objects.get(recipient=author, kind=Notification.Kind.REPLY)
    assert "izoh_replier" in n.title and f"#review-{root.id}" in n.url
    # O'z izohiga o'zi javob yozsa — yangi bildirishnoma YO'Q
    client.force_login(author)
    client.post(
        reverse("drama:add_review", args=[movie.id]), {"text": "O'zimga", "parent": root.id}
    )
    assert Notification.objects.filter(recipient=author, kind=Notification.Kind.REPLY).count() == 1


@pytest.mark.django_db
def test_reply_foreign_or_hidden_parent_404(client):
    """Parent boshqa kinoniki yoki moderatsiyada yashirilgan bo'lsa — 404, reply yaratilmaydi."""
    movie, author, replier = _reply_fixtures()
    other = Movie.objects.create(title="BoshqaKino", description="x", country="KR")
    foreign = Review.objects.create(user=author, movie=other, text="Boshqa kino izohi")
    hidden = Review.objects.create(user=author, movie=movie, text="Yashirin", is_hidden=True)
    client.force_login(replier)
    url = reverse("drama:add_review", args=[movie.id])
    assert client.post(url, {"text": "x", "parent": foreign.id}).status_code == 404
    assert client.post(url, {"text": "x", "parent": hidden.id}).status_code == 404
    assert client.post(url, {"text": "x", "parent": "abc"}).status_code == 404
    assert not Review.objects.filter(text="x").exists()


@pytest.mark.django_db
def test_reply_requires_auth_401(client):
    movie, author, _replier = _reply_fixtures()
    root = Review.objects.create(user=author, movie=movie, text="Root")
    resp = client.post(
        reverse("drama:add_review", args=[movie.id]), {"text": "anon", "parent": root.id}
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_review_web_throttle_kept_429(client):
    """AC: throttle saqlangan — RATELIMIT_RATES['review'] limitidan keyin 429."""
    from django.conf import settings as dj_settings

    movie, _author, replier = _reply_fixtures()
    client.force_login(replier)
    url = reverse("drama:add_review", args=[movie.id])
    limit = int(dj_settings.RATELIMIT_RATES["review"].split("/")[0])
    statuses = [client.post(url, {"text": f"fikr {i}"}).status_code for i in range(limit + 1)]
    assert 429 in statuses


# --- Signal receiverlar (drama/signals.py) + crossover chegara holatlari [drama_test_1] ---


@pytest.mark.django_db
def test_catalog_version_bumped_on_movie_delete():
    from django.core.cache import cache

    from drama.cache import catalog_version

    movie = Movie.objects.create(title="DelKino", description="x", country="KR")
    cache.clear()
    before = catalog_version()
    movie.delete()  # post_delete ham invalidatsiya qiladi
    assert catalog_version() > before


@pytest.mark.django_db
def test_catalog_version_bumped_on_light_catalog_models():
    """Genre/Category saqlash ham katalog keshini bump qiladi (per-sender ulanish)."""
    from django.core.cache import cache

    from drama.cache import catalog_version
    from drama.models import Category, Genre

    cache.clear()
    for obj in (
        Genre(name="SigJanr", slug="sig-janr"),
        Category(name="SigKat", slug="sig-kat"),
    ):
        before = catalog_version()
        obj.save()
        assert catalog_version() > before, type(obj).__name__


@pytest.mark.django_db
def test_trending_recompute_only_for_movie_and_tag(django_capture_on_commit_callbacks):
    """Trending qayta-hisob faqat Movie|Tag saqlanganda — Genre'da rejalashtirilmaydi."""
    from drama.models import Genre

    with django_capture_on_commit_callbacks() as cb_genre:
        Genre.objects.create(name="TrJanr", slug="tr-janr")
    assert "recompute_trending_tags" not in repr(cb_genre)

    with django_capture_on_commit_callbacks() as cb_tag:
        Tag.objects.create(name="TrTeg", slug="tr-teg")
    assert "recompute_trending_tags" in repr(cb_tag)


@pytest.mark.django_db
def test_search_vector_only_on_forward_actor_m2m(django_capture_on_commit_callbacks):
    """actors m2m: forward (movie.actors.add) FTS rejalashtiradi; reverse
    (actor.acted_movies.add) instance=Actor bo'lgani uchun SKIP — aks holda
    Actor.pk Movie.pk deb yuborilardi."""
    from drama.models import Actor

    movie = Movie.objects.create(title="FwdKino", description="x", country="KR")
    a1 = Actor.objects.create(name="A1", slug="sig-a1")
    a2 = Actor.objects.create(name="A2", slug="sig-a2")

    with django_capture_on_commit_callbacks() as fwd:
        movie.actors.add(a1)
    assert "update_search_vector" in repr(fwd)

    with django_capture_on_commit_callbacks() as rev:
        a2.acted_movies.add(movie)
    assert "update_search_vector" not in repr(rev)


@pytest.mark.django_db
def test_tags_clear_bumps_catalog_version():
    from django.core.cache import cache

    from drama.cache import catalog_version

    movie = Movie.objects.create(title="ClrKino", description="x", country="KR")
    tag = Tag.objects.create(name="ClrTeg", slug="clr-teg")
    movie.tags.add(tag)
    cache.clear()
    before = catalog_version()
    movie.tags.clear()  # post_clear tarmog'i
    assert catalog_version() > before


@pytest.mark.django_db
def test_queue_next_crosses_season_boundary(client):
    """Fasl chegarasi: S1 tugasa S2'ning birinchi qismi navbatga tushadi —
    davomiylik episode_number bo'yicha, fasl FK to'siq emas."""
    movie, ep1, user = _movie_episode_user(title="SeasonX", username="season_user")
    s1 = Season.objects.create(movie=movie, number=1)
    s2 = Season.objects.create(movie=movie, number=2)
    Episode.objects.filter(pk=ep1.pk).update(season=s1)
    ep2 = Episode.objects.create(movie=movie, episode_number=2, title="S2E1", season=s2)
    client.force_login(user)
    client.post(
        reverse("drama:save_watch_progress", args=[ep1.id]),
        {"position_seconds": 95, "duration_seconds": 100},
    )
    assert WatchProgress.objects.filter(user=user, episode=ep2, completed=False).exists()


@pytest.mark.django_db
def test_queue_next_queues_vip_locked_episode(client):
    """Navbatga olish != ko'rish ruxsati: keyingi qism VIP-qulf bo'lsa ham 0% qator
    ochiladi (gate playback service'da qoladi) — ataylab shunday."""
    movie, ep1, user = _movie_episode_user(title="VipQ", username="vipq_user")
    Movie.objects.filter(pk=movie.pk).update(is_vip=True)
    Episode.objects.filter(pk=ep1.pk).update(episode_number=10)
    ep11 = Episode.objects.create(movie=movie, episode_number=11, title="E11")
    client.force_login(user)
    client.post(
        reverse("drama:save_watch_progress", args=[ep1.id]),
        {"position_seconds": 95, "duration_seconds": 100},
    )
    assert WatchProgress.objects.filter(user=user, episode=ep11).exists()


@pytest.mark.django_db
def test_no_queue_when_progress_not_completed(client):
    """50% progress — completed emas -> keyingi qism NAVBATGA TUSHMAYDI."""
    movie, ep1, user = _movie_episode_user(title="HalfW", username="half_user")
    ep2 = Episode.objects.create(movie=movie, episode_number=2, title="E2")
    client.force_login(user)
    client.post(
        reverse("drama:save_watch_progress", args=[ep1.id]),
        {"position_seconds": 50, "duration_seconds": 100},
    )
    assert not WatchProgress.objects.filter(user=user, episode=ep2).exists()


@pytest.mark.django_db
def test_continue_watching_latest_per_movie_across_movies():
    """Ikki serial, har birida 2 chala qism -> ro'yxatda AYNAN 2 qator (har
    serialdan eng so'nggisi), tartib eng yaqin harakat birinchi. updated_at
    .update() bilan deterministik (auto_now granulyarlik gotcha'si)."""
    from users.selectors import continue_watching

    now = timezone.now()
    user = User.objects.create_user(username="cw_user", password="pass12345")
    rows = {}
    for title in ("CW-A", "CW-B"):
        movie = Movie.objects.create(title=title, description="x", country="KR")
        for n in (1, 2):
            ep = Episode.objects.create(movie=movie, episode_number=n, title=f"E{n}")
            rows[(title, n)] = WatchProgress.objects.create(
                user=user, episode=ep, position_seconds=10, duration_seconds=100
            )
    WatchProgress.objects.filter(pk=rows[("CW-A", 1)].pk).update(
        updated_at=now - timedelta(minutes=30)
    )
    WatchProgress.objects.filter(pk=rows[("CW-A", 2)].pk).update(
        updated_at=now - timedelta(minutes=20)
    )
    WatchProgress.objects.filter(pk=rows[("CW-B", 2)].pk).update(
        updated_at=now - timedelta(minutes=10)
    )
    WatchProgress.objects.filter(pk=rows[("CW-B", 1)].pk).update(
        updated_at=now - timedelta(minutes=5)
    )
    got = [wp.episode_id for wp in continue_watching(user)]
    assert got == [
        rows[("CW-B", 1)].episode_id,
        rows[("CW-A", 2)].episode_id,
    ]


# --- V2B-T2: izoh reaksiyalari (like) + saralash + komment-forma mavjudligi ---


QUERYCOUNT_REVIEWS_PAGE = (
    7  # sessiya+user+movie+roots(Exists)+replies+paginator+blok-ro'yxati [V2B-T5]
)


def _review_user(username="liker"):
    movie = Movie.objects.create(title=f"LikeKino {username}", description="x", country="KR")
    author = User.objects.create_user(username=f"a_{username}", password="pass12345")
    review = Review.objects.create(user=author, movie=movie, text="Zo'r!")
    user = User.objects.create_user(username=username, password="pass12345")
    return movie, review, user


@pytest.mark.django_db
def test_like_toggle_idempotent(client):
    """[V2B-T2 AC] Birinchi POST like qo'shadi, ikkinchisi QAYTARADI (toggle)."""
    from drama.models import ReviewReaction

    _movie, review, user = _review_user("tog_user")
    client.force_login(user)
    url = reverse("drama:toggle_review_like", args=[review.id])

    resp = client.post(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    review.refresh_from_db()
    assert review.like_count == 1
    assert ReviewReaction.objects.filter(user=user, review=review).exists()
    assert "fas fa-heart" in resp.content.decode()  # yoqilgan holat

    resp2 = client.post(url, HTTP_HX_REQUEST="true")
    review.refresh_from_db()
    assert review.like_count == 0
    assert not ReviewReaction.objects.filter(user=user, review=review).exists()
    assert "far fa-heart" in resp2.content.decode()  # o'chirilgan holat


@pytest.mark.django_db
def test_like_anonymous_401(client):
    _movie, review, _user = _review_user("anon_like")
    resp = client.post(reverse("drama:toggle_review_like", args=[review.id]))
    assert resp.status_code == 401


@pytest.mark.django_db
def test_like_hidden_review_404(client):
    _movie, review, user = _review_user("hid_like")
    Review.objects.filter(pk=review.pk).update(is_hidden=True)
    client.force_login(user)
    resp = client.post(reverse("drama:toggle_review_like", args=[review.id]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_like_count_two_users(client):
    """[V2B-T2 AC] Sanoq F() bilan: ikki user -> 2; bittasi qaytarsa -> 1."""
    _movie, review, u1 = _review_user("two_a")
    u2 = User.objects.create_user(username="two_b", password="pass12345")
    url = reverse("drama:toggle_review_like", args=[review.id])
    client.force_login(u1)
    client.post(url)
    client.force_login(u2)
    client.post(url)
    review.refresh_from_db()
    assert review.like_count == 2
    client.post(url)  # u2 qaytardi
    review.refresh_from_db()
    assert review.like_count == 1


@pytest.mark.django_db
def test_reviews_sort_top_and_default(client):
    """[V2B-T2 AC] ?sort=top -> like_count bo'yicha; default -> yangi (-id)."""
    movie = Movie.objects.create(title="SortKino", description="x", country="KR")
    a = User.objects.create_user(username="sort_a", password="pass12345")
    r1 = Review.objects.create(user=a, movie=movie, text="r1")
    r2 = Review.objects.create(user=a, movie=movie, text="r2")
    r3 = Review.objects.create(user=a, movie=movie, text="r3")
    Review.objects.filter(pk=r1.pk).update(like_count=2)
    Review.objects.filter(pk=r2.pk).update(like_count=5)

    url = reverse("drama:movie_reviews", args=[movie.slug])
    top = client.get(url + "?sort=top")
    assert [r.id for r in top.context["reviews"]] == [r2.id, r1.id, r3.id]
    assert top.context["sort"] == "top"

    new = client.get(url)
    assert [r.id for r in new.context["reviews"]] == [r3.id, r2.id, r1.id]
    assert new.context["sort"] == "new"


@pytest.mark.django_db
def test_reviews_page_query_count(client):
    """[V2B-T2 AC] auth user uchun so'rovlar soni QOTIRILGAN — user_liked Exists
    subquery asosiy so'rov ichida (alohida reaksiya-so'rovi YO'Q)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    movie, review, user = _review_user("nq_user")
    author2 = User.objects.create_user(username="nq_a2", password="pass12345")
    Review.objects.create(user=author2, movie=movie, text="root2")
    Review.objects.create(user=author2, movie=movie, text="rep", parent=review)
    client.force_login(user)
    url = reverse("drama:movie_reviews", args=[movie.slug])
    client.get(url)  # birinchi chaqiruv (sessiya va h.k. barqarorlashsin)
    with CaptureQueriesContext(connection) as ctx:
        client.get(url)
    assert len(ctx) == QUERYCOUNT_REVIEWS_PAGE, [q["sql"][:80] for q in ctx]


@pytest.mark.django_db
def test_classic_page_has_comment_form(client):
    """[comment-fix] Klassik sahifada forma, ro'yxat va comments.js bo'lishi SHART."""
    from drama.models import Category

    cat = Category.objects.create(
        name="KinoKlassik", slug="kino-klassik-t", player_type=Category.PlayerType.CLASSIC
    )
    movie = Movie.objects.create(
        title="ClassicForm", description="x", country="KR", category=cat, poster=_uploaded()
    )
    user = User.objects.create_user(username="cform", password="pass12345")
    client.force_login(user)
    html = client.get(movie.get_absolute_url()).content.decode()
    assert 'id="rCommentForm"' in html
    assert 'id="rCommentList"' in html
    assert "js/comments.js" in html


@pytest.mark.django_db
def test_reviews_page_has_form_and_like_button(client):
    """[comment-fix + V2B-T2] Reviews sahifasi: forma + comments.js + like tugmasi."""
    movie, review, user = _review_user("rvform")
    client.force_login(user)
    html = client.get(reverse("drama:movie_reviews", args=[movie.slug])).content.decode()
    assert 'id="rCommentForm"' in html
    assert "js/comments.js" in html
    assert f"/review/{review.id}/like/" in html


@pytest.mark.django_db
def test_reels_page_includes_comments_js(client):
    """[comment-fix] Reels sahifa comments.js'ni yuklaydi (player.js'dan ajratildi)."""
    movie = Movie.objects.create(title="ReelsJs", description="x", country="KR", poster=_uploaded())
    html = client.get(movie.get_absolute_url()).content.decode()
    assert "js/comments.js" in html


@pytest.mark.django_db
def test_storage_cache_headers_p9t3():
    """[P9-T3 AC] Static: 1 yil + immutable (Manifest-hash nomlar); media: 30 kun,
    immutable EMAS (default.jpg kabi turg'un nomlar bor)."""
    from config.custom_storage import CustomMediaStorage, CustomStaticStorage

    static_cc = CustomStaticStorage.object_parameters["cache_control"]
    media_cc = CustomMediaStorage.object_parameters["cache_control"]
    assert "max-age=31536000" in static_cc and "immutable" in static_cc
    assert "max-age=2592000" in media_cc and "immutable" not in media_cc


# --- V2B-T3: epizod-darajali izohlar + spoyler ---


def _ep_movie(title="EpKom", n=2):
    movie = Movie.objects.create(title=title, description="x", country="KR", poster=_uploaded())
    eps = [
        Episode.objects.create(movie=movie, episode_number=i, title=f"E{i}")
        for i in range(1, n + 1)
    ]
    return movie, eps


@pytest.mark.django_db
def test_add_review_with_episode_and_spoiler(client):
    """Forma episode + is_spoiler qabul qiladi; qism SHU kinoniki."""
    movie, (ep1, _ep2) = _ep_movie("EpYoz")
    user = User.objects.create_user(username="ep_user", password="pass12345")
    client.force_login(user)
    client.post(
        reverse("drama:add_review", args=[movie.id]),
        {"text": "1-qism zo'r!", "episode": ep1.id, "is_spoiler": "1"},
    )
    r = Review.objects.get(text="1-qism zo'r!")
    assert r.episode_id == ep1.id
    assert r.is_spoiler is True


@pytest.mark.django_db
def test_add_review_foreign_episode_404(client):
    """Boshqa kinoning qismi bilan yozib bo'lmaydi — 404, izoh YARATILMAYDI."""
    movie, _eps = _ep_movie("EpAsl")
    _other, (oep, _o2) = _ep_movie("EpBegona")
    user = User.objects.create_user(username="ep_yot", password="pass12345")
    client.force_login(user)
    resp = client.post(
        reverse("drama:add_review", args=[movie.id]),
        {"text": "xato", "episode": oep.id},
    )
    assert resp.status_code == 404
    assert not Review.objects.filter(text="xato").exists()


@pytest.mark.django_db
def test_reply_inherits_parent_episode(client):
    """Javob threadi bir joyda: reply'ning episode'i ROOT'dan meros (POST'dagi emas)."""
    movie, (ep1, ep2) = _ep_movie("EpMeros")
    author = User.objects.create_user(username="ep_a", password="pass12345")
    root = Review.objects.create(user=author, movie=movie, text="root", episode=ep1)
    replier = User.objects.create_user(username="ep_r", password="pass12345")
    client.force_login(replier)
    client.post(
        reverse("drama:add_review", args=[movie.id]),
        {"text": "javob", "parent": root.id, "episode": ep2.id},  # ep2 BERILSA HAM
    )
    reply = Review.objects.get(text="javob")
    assert reply.parent_id == root.id
    assert reply.episode_id == ep1.id  # root'niki g'olib


@pytest.mark.django_db
def test_comments_partial_episode_scope(client):
    """?episode=<id>: shu qism + UMUMIY (null) chiqadi, boshqa qismniki CHIQMAYDI."""
    movie, (ep1, ep2) = _ep_movie("EpFiltr")
    a = User.objects.create_user(username="ep_f", password="pass12345")
    Review.objects.create(user=a, movie=movie, text="umumiy-izoh")
    Review.objects.create(user=a, movie=movie, text="birinchi-qism-izoh", episode=ep1)
    Review.objects.create(user=a, movie=movie, text="ikkinchi-qism-izoh", episode=ep2)

    url = reverse("drama:movie_comments", args=[movie.id])
    html = client.get(url, {"episode": ep1.id}).content.decode()
    assert "umumiy-izoh" in html and "birinchi-qism-izoh" in html
    assert "ikkinchi-qism-izoh" not in html

    html_all = client.get(url).content.decode()
    assert "ikkinchi-qism-izoh" in html_all and "umumiy-izoh" in html_all

    # begona qism -> 404
    _o, (oep, _o2) = _ep_movie("EpFiltrBegona")
    assert client.get(url, {"episode": oep.id}).status_code == 404


@pytest.mark.django_db
def test_detail_default_scope_is_current_episode(client):
    """Detail sahifada default sheet ro'yxati = aktiv qism + umumiy (AC-1)."""
    movie, (ep1, ep2) = _ep_movie("EpDefault")
    a = User.objects.create_user(username="ep_d", password="pass12345")
    Review.objects.create(user=a, movie=movie, text="umumiy-d")
    Review.objects.create(user=a, movie=movie, text="ep1-d", episode=ep1)
    Review.objects.create(user=a, movie=movie, text="ep2-d", episode=ep2)
    resp = client.get(movie.get_absolute_url() + "?episode=1")
    texts = [r.text for r in resp.context["sheet_reviews"]]
    assert "umumiy-d" in texts and "ep1-d" in texts
    assert "ep2-d" not in texts


@pytest.mark.django_db
def test_spoiler_rendered_with_details_fallback(client):
    """Spoyler <details> bilan yopiq keladi (JS'siz ham ishlaydi — AC-2)."""
    movie, (ep1, _ep2) = _ep_movie("EpSpoyler")
    a = User.objects.create_user(username="ep_s", password="pass12345")
    Review.objects.create(user=a, movie=movie, text="katta-sir-matni", is_spoiler=True)
    Review.objects.create(user=a, movie=movie, text="oddiy-matn")
    html = client.get(reverse("drama:movie_comments", args=[movie.id])).content.decode()
    assert "Spoyler — ochish uchun bosing" in html
    assert "<details>" in html
    assert "katta-sir-matni" in html  # matn details ichida (yashirin, DOM'da bor)
    # oddiy izoh spoyler o'ramisiz
    assert html.count("Spoyler — ochish uchun bosing") == 1


@pytest.mark.django_db
def test_old_reviews_unbroken_episode_null(client):
    """Eski izohlar (episode=null) buzilmaydi: umumiy sifatida hamma scope'da (AC-3)."""
    movie, (ep1, ep2) = _ep_movie("EpEski")
    a = User.objects.create_user(username="ep_o", password="pass12345")
    r = Review.objects.create(user=a, movie=movie, text="eski-izoh")
    assert r.episode is None and r.is_spoiler is False
    url = reverse("drama:movie_comments", args=[movie.id])
    assert "eski-izoh" in client.get(url, {"episode": ep1.id}).content.decode()
    assert "eski-izoh" in client.get(url, {"episode": ep2.id}).content.decode()
    assert "eski-izoh" in client.get(url).content.decode()


# --- V2B-T5: bloklangan muallif izohlari collapse + reply-taqiq ---


@pytest.mark.django_db
def test_blocked_author_comment_collapsed(client):
    """AC-2: blocker uchun bloklangan muallif izohi collapse (<details>) keladi;
    boshqa viewer va anonim uchun ODDIY ko'rinadi."""
    from users.models import UserBlock

    movie = Movie.objects.create(title="BlokKino", description="x", country="KR")
    author = User.objects.create_user(username="blk_author", password="pass12345")
    Review.objects.create(user=author, movie=movie, text="blok-matn-x")
    viewer = User.objects.create_user(username="blk_viewer", password="pass12345")
    UserBlock.objects.create(blocker=viewer.profile, blocked=author.profile)

    url = reverse("drama:movie_comments", args=[movie.id])
    client.force_login(viewer)
    html = client.get(url).content.decode()
    assert "Bloklangan foydalanuvchi izohi" in html  # collapse chip
    assert "blok-matn-x" in html  # matn details ICHIDA (DOM'da bor, yopiq)

    client.logout()
    html_anon = client.get(url).content.decode()
    assert "Bloklangan foydalanuvchi izohi" not in html_anon
    assert "blok-matn-x" in html_anon


@pytest.mark.django_db
def test_reply_to_blocked_author_403_one_way(client):
    """Blocker bloklangan muallifga javob yoza olmaydi (403); TESKARISI mumkin
    (bir tomonlama mute)."""
    from users.models import UserBlock

    movie = Movie.objects.create(title="BlokReply", description="x", country="KR")
    author = User.objects.create_user(username="blkr_author", password="pass12345")
    root = Review.objects.create(user=author, movie=movie, text="root-blk")
    viewer = User.objects.create_user(username="blkr_viewer", password="pass12345")
    UserBlock.objects.create(blocker=viewer.profile, blocked=author.profile)

    client.force_login(viewer)
    resp = client.post(
        reverse("drama:add_review", args=[movie.id]), {"text": "taqiq", "parent": root.id}
    )
    assert resp.status_code == 403
    assert not Review.objects.filter(text="taqiq").exists()

    # Teskari yo'nalish: author viewer'ning izohiga javob yoza OLADI
    viewer_root = Review.objects.create(user=viewer, movie=movie, text="viewer-root")
    client.force_login(author)
    client.post(
        reverse("drama:add_review", args=[movie.id]),
        {"text": "erkin-javob", "parent": viewer_root.id},
    )
    assert Review.objects.filter(text="erkin-javob", parent=viewer_root).exists()


# --- V2E-T1: epizod subtitrlari (VTT) ---


def _vtt(name="sub.vtt", content=b"WEBVTT\n\n00:00.000 --> 00:02.000\nSalom\n"):
    return SimpleUploadedFile(name, content, content_type="text/vtt")


def test_subtitle_validator_rules():
    """[V2E-T1 AC] faqat .vtt + WEBVTT magic (BOM'ga toqat) + 2MB limit."""
    from core.validators import SubtitleFileValidator

    v = SubtitleFileValidator(max_mb=2)
    v(_vtt())  # sof VTT — o'tadi
    v(_vtt(content=b"\xef\xbb\xbfWEBVTT\nok"))  # UTF-8 BOM bilan ham o'tadi
    with pytest.raises(ValidationError):
        v(_vtt(name="sub.srt"))  # kengaytma
    with pytest.raises(ValidationError):
        v(_vtt(content=b"<html>xss</html>"))  # magic yo'q (stored-XSS himoya)
    big = SimpleUploadedFile(
        "big.vtt", b"WEBVTT\n" + b"a" * (2 * 1024 * 1024 + 1), content_type="text/vtt"
    )
    with pytest.raises(ValidationError):
        v(big)


@pytest.mark.django_db
def test_subtitle_unique_per_episode_lang():
    from django.db import IntegrityError, transaction

    from drama.models import EpisodeSubtitle

    _movie_obj, (ep1, _ep2) = _ep_movie("SubUniq")
    sub = EpisodeSubtitle.objects.create(episode=ep1, lang="uz", vtt_file=_vtt())
    assert sub.display_label == "O'zbekcha"  # label bo'sh -> til nomi
    with pytest.raises(IntegrityError), transaction.atomic():
        EpisodeSubtitle.objects.create(episode=ep1, lang="uz", vtt_file=_vtt("s2.vtt"))


@pytest.mark.django_db
def test_reels_page_renders_tracks_for_anonymous(client, bunny):
    """[V2E-T1 AC] <track> + crossorigin + CC tugma — anonim uchun ham.

    `bunny` fixture SHART: use_bunny=True bo'lishi is_configured()ga bog'liq —
    usiz lokalda .env qiymatlari sizib testni yashil, CI'da esa qizil qilardi
    (V2A-T2 gotcha'sining aynan o'zi)."""
    from drama.models import EpisodeSubtitle

    movie, (ep1, ep2) = _ep_movie("SubReels")
    # Ikkala qism ham video-manbali: 2-qism "sheet bor, subtitr guruhi yo'q"
    # holatini qoplaydi
    Episode.objects.filter(pk__in=[ep1.pk, ep2.pk]).update(bunny_video_id="subvid1")
    EpisodeSubtitle.objects.create(episode=ep1, lang="uz", vtt_file=_vtt())
    EpisodeSubtitle.objects.create(episode=ep1, lang="ru", vtt_file=_vtt("ru.vtt"))
    html = client.get(movie.get_absolute_url() + "?episode=1").content.decode()
    assert html.count("<track ") == 2
    assert 'srclang="uz"' in html and 'srclang="ru"' in html
    assert 'crossorigin="anonymous"' in html
    # [V2E-T1 UX] sozlamalar sheet: rail tugma + radio-optsiyalar
    assert 'id="playerSheet"' in html
    assert 'title="Sozlamalar"' in html
    assert 'data-set="subtitle" data-val="uz"' in html
    assert 'data-set="subtitle" data-val=""' in html  # O'chiq optsiyasi
    assert 'data-set="quality" data-val="auto"' in html  # bunny -> Avto/FHD

    # subtitrsiz qism: track/crossorigin YO'Q; sheet BOR (sifat), subtitr guruhi YO'Q
    html2 = client.get(movie.get_absolute_url() + "?episode=2").content.decode()
    assert "<track " not in html2
    assert 'crossorigin="anonymous"' not in html2
    assert 'id="playerSheet"' in html2
    assert 'data-set="quality"' in html2
    assert 'data-set="subtitle"' not in html2


@pytest.mark.django_db
def test_classic_page_renders_tracks(client):
    from drama.models import Category, EpisodeSubtitle

    cat = Category.objects.create(
        name="SubKlassik", slug="sub-klassik", player_type=Category.PlayerType.CLASSIC
    )
    movie, (ep1, _ep2) = _ep_movie("SubClassic")
    Movie.objects.filter(pk=movie.pk).update(category=cat)
    EpisodeSubtitle.objects.create(episode=ep1, lang="en", vtt_file=_vtt())
    html = client.get(movie.get_absolute_url() + "?episode=1").content.decode()
    assert 'srclang="en"' in html
    assert 'id="cpSubBtn"' in html
    assert 'id="cpSubMenu"' in html  # [V2E-T1 UX] menyu (cycle emas)
    assert 'data-sub="en"' in html
    assert 'crossorigin="anonymous"' in html


# --- V2E-T2: intro-skip markerlari + keyingi-qism countdown ---


@pytest.mark.django_db
def test_intro_marker_validation():
    """[V2E-T2 AC] intro_end <= intro_start -> ValidationError (admin formasi to'xtatadi)."""
    _m, (ep1, _e2) = _ep_movie("IntroVal")
    ep1.intro_start = 30
    ep1.intro_end = 10
    with pytest.raises(ValidationError):
        ep1.full_clean()
    ep1.intro_end = 45
    ep1.full_clean()  # to'g'ri oraliq — o'tadi


@pytest.mark.django_db
def test_reels_marker_json_and_overlays(client, bunny):
    """[V2E-T2 AC] Data-JSON'da introStart/End; skip-tugma faqat marker borida;
    countdown overlay keyingi qism borida."""
    movie, (ep1, ep2) = _ep_movie("IntroReels")
    Episode.objects.filter(pk__in=[ep1.pk, ep2.pk]).update(bunny_video_id="introvid")
    Episode.objects.filter(pk=ep1.pk).update(intro_start=5, intro_end=20)

    html = client.get(movie.get_absolute_url() + "?episode=1").content.decode()
    assert '"introStart": 5' in html and '"introEnd": 20' in html
    assert 'id="rSkipIntro"' in html
    assert 'id="rNextOverlay"' in html  # keyingi qism (2) bor
    assert 'id="rNextCount"' in html

    # 2-qism: marker YO'Q -> null + tugma yo'q; keyingi qism ham yo'q -> overlay yo'q
    html2 = client.get(movie.get_absolute_url() + "?episode=2").content.decode()
    assert '"introStart": null' in html2 and '"introEnd": null' in html2
    assert 'id="rSkipIntro"' not in html2
    assert 'id="rNextOverlay"' not in html2


@pytest.mark.django_db
def test_classic_marker_json_and_skip(client, bunny):
    from drama.models import Category

    cat = Category.objects.create(
        name="IntroKlassik", slug="intro-klassik", player_type=Category.PlayerType.CLASSIC
    )
    movie, (ep1, _ep2) = _ep_movie("IntroClassic")
    Movie.objects.filter(pk=movie.pk).update(category=cat)
    Episode.objects.filter(pk=ep1.pk).update(
        bunny_video_id="introvidc", intro_start=3, intro_end=12
    )
    html = client.get(movie.get_absolute_url() + "?episode=1").content.decode()
    assert '"introStart": 3' in html and '"introEnd": 12' in html
    assert 'id="cpSkipIntro"' in html
    assert 'id="cpNextOverlay"' in html  # klassikda azaldan bor


@pytest.mark.django_db
def test_admin_has_intro_fields():
    """[V2E-T2 AC] EpisodeAdmin fieldsets'da intro maydonlari bor."""
    from drama.admin import EpisodeAdmin

    fields = []
    for _name, opts in EpisodeAdmin.fieldsets:
        for f in opts.get("fields", ()):
            fields.extend(f if isinstance(f, (list, tuple)) else [f])
    assert "intro_start" in fields and "intro_end" in fields


# --- V2E-T3: treyler UI (FAQAT klassik pleyer) ---


def _classic_movie(title="TreylerKino", trailer_id="trailer123"):
    from drama.models import Category

    cat = Category.objects.create(
        name=f"Klassik-{title}",
        slug=f"klassik-{title.lower()}",
        player_type=Category.PlayerType.CLASSIC,
    )
    movie, (ep1, _ep2) = _ep_movie(title)
    Movie.objects.filter(pk=movie.pk).update(
        category=cat, bunny_video_id="mainvid", bunny_trailer_id=trailer_id
    )
    return Movie.objects.get(pk=movie.pk)


@pytest.mark.django_db
def test_trailer_button_and_modal_on_classic(client, bunny):
    """[V2E-T3 AC] bunny_trailer_id bor klassik kinoda Treyler tugma + modal;
    classicData'da trailerHls (imzoli HLS URL)."""
    movie = _classic_movie()
    html = client.get(movie.get_absolute_url()).content.decode()
    assert 'id="cpTrailerBtn"' in html
    assert 'id="cpTrailerModal"' in html
    assert 'id="cpTrailerVideo"' in html
    # escapejs "-" -> - qiladi (JSON.parse'da to'g'ri) -> tail bo'yicha tekshiramiz
    assert "trailerHls" in html
    assert "trailer123/playlist.m3u8" in html


@pytest.mark.django_db
def test_no_trailer_when_id_empty(client, bunny):
    """[V2E-T3 AC] bunny_trailer_id bo'sh -> Treyler tugma/modal YO'Q."""
    movie = _classic_movie(trailer_id="")
    html = client.get(movie.get_absolute_url()).content.decode()
    assert 'id="cpTrailerBtn"' not in html
    assert 'id="cpTrailerModal"' not in html


@pytest.mark.django_db
def test_trailer_not_rendered_on_reels(client, bunny):
    """[V2E-T3] Reels kinoda trailer_id bo'lsa ham treyler UI CHIQMAYDI
    (foydalanuvchi qarori: faqat klassik). Kontekstda ham hisoblanmaydi."""
    movie, (ep1, _ep2) = _ep_movie("ReelsTreyler")  # kategoriyasiz -> reels
    Episode.objects.filter(pk=ep1.pk).update(bunny_video_id="rmain")
    Movie.objects.filter(pk=movie.pk).update(bunny_trailer_id="trailerX")
    resp = client.get(movie.get_absolute_url())
    html = resp.content.decode()
    assert 'id="cpTrailerBtn"' not in html
    assert "trailerHls" not in html
    assert "trailer_hls" not in resp.context or not resp.context["trailer_hls"]


@pytest.mark.django_db
def test_trailer_gating_free_for_anonymous(client, bunny):
    """[V2E-T3 AC] Treyler anonim uchun ham ochiq (marketing — gating'siz)."""
    movie = _classic_movie(title="VipTreyler")
    Movie.objects.filter(pk=movie.pk).update(is_vip=True)  # asosiy video VIP
    resp = client.get(movie.get_absolute_url())  # anonim
    html = resp.content.decode()
    # Treyler tugmasi VIP'dan qat'i nazar ko'rinadi (asosiy video emas)
    assert 'id="cpTrailerBtn"' in html
    assert resp.context["trailer_hls"]


# --- admin-ux: EpisodeInline'da bunny_video_id tahrirlanadi ---


def test_episode_inline_bunny_id_editable():
    """[admin-ux] Kino ichida (EpisodeInline) bunny_video_id QO'LDA yozilishi kerak
    — katta seriallarni Bunny'ga qo'lda yuklab GUID kiritish oqimi uchun.
    Regressiya guard: readonly_fields'ga qaytib kirmasin."""
    from drama.admin import EpisodeInline

    assert "bunny_video_id" in EpisodeInline.fields
    assert "bunny_video_id" not in EpisodeInline.readonly_fields
    # holat-badge esa readonly qoladi (avtomatik hisoblanadi)
    assert "display_upload_status" in EpisodeInline.readonly_fields


@pytest.mark.django_db
def test_episode_inline_renders_editable_input(client):
    """Kino tahrirlash sahifasida bunny_video_id <input> (readonly emas) bo'lib chiqadi."""
    from django.contrib.auth.models import User

    admin_user = User.objects.create_superuser("admin_bux", "a@b.uz", "pass12345")
    client.force_login(admin_user)
    movie, (ep1, _ep2) = _ep_movie("InlineBux")
    resp = client.get(reverse("admin:drama_movie_change", args=[movie.id]))
    html = resp.content.decode()
    # inline'dagi qism uchun bunny_video_id nomli tahrirlanadigan input bo'lishi kerak
    assert 'name="episodes-0-bunny_video_id"' in html
