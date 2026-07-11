"""V2A-T1 testlari — yangi-qism fan-out, opt-out, idempotentlik, webhook wiring."""

import pytest
from django.urls import reverse

from drama.factories import EpisodeFactory, MovieFactory
from drama.models import Movie, UploadStatus
from drama.tasks import notify_new_episode_followers
from users.factories import UserFactory
from users.models import Notification, UserMovieList
from users.services.notifications import unread_count


def _follower(movie, status=UserMovieList.WATCHING, opt_out=False):
    user = UserFactory()
    profile = user.profile
    if opt_out:
        profile.notify_new_episode = False
        profile.save(update_fields=["notify_new_episode"])
    UserMovieList.objects.create(profile=profile, movie=movie, status=status)
    return user


@pytest.mark.django_db
def test_fanout_watching_planned_only_and_badge():
    """Ko'ryapman/Rejada oladi; tugatgan va opt-out olmaydi; bell badge oshadi."""
    movie = MovieFactory()  # default published
    ep = EpisodeFactory(movie=movie, episode_number=11)
    u_watch = _follower(movie, UserMovieList.WATCHING)
    u_plan = _follower(movie, UserMovieList.PLANNED)
    u_done = _follower(movie, 2)  # tugatgan — kuzatuvchi emas
    u_out = _follower(movie, UserMovieList.WATCHING, opt_out=True)

    sent = notify_new_episode_followers.apply(args=[ep.pk]).result

    assert sent == 2
    notes = Notification.objects.filter(kind=Notification.Kind.NEW_EPISODE)
    assert {n.recipient_id for n in notes} == {u_watch.id, u_plan.id}
    note = notes.get(recipient=u_watch)
    assert movie.title in note.title
    assert "11-qism" in note.title
    assert note.url.endswith("?episode=11")
    # header bell badge manbai (notifications_unread context) [AC-2]
    assert unread_count(u_watch) == 1
    assert unread_count(u_done) == 0
    assert unread_count(u_out) == 0


@pytest.mark.django_db
def test_fanout_idempotent():
    """Webhook + poll ikkalasi chaqirsa ham xabar bir marta [AC-4]."""
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie)
    _follower(movie)
    assert notify_new_episode_followers.apply(args=[ep.pk]).result == 1
    assert notify_new_episode_followers.apply(args=[ep.pk]).result == 0
    assert Notification.objects.count() == 1
    ep.refresh_from_db()
    assert ep.followers_notified_at is not None


@pytest.mark.django_db
def test_draft_movie_skipped_without_marking():
    movie = MovieFactory(status=Movie.Status.DRAFT)
    ep = EpisodeFactory(movie=movie)
    _follower(movie)
    assert notify_new_episode_followers.apply(args=[ep.pk]).result == 0
    assert Notification.objects.count() == 0
    ep.refresh_from_db()
    assert ep.followers_notified_at is None  # keyin qayta trigger qilish mumkin


@pytest.mark.django_db
def test_fanout_query_count_constant(django_assert_num_queries):
    """N+1 yo'q [AC-1]: 20 obunachi ham bitta bulk_create bilan ketadi."""
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie)
    for _ in range(20):
        _follower(movie)
    # qulf+o'qish (1) + follower ro'yxati (1) + save (1) + bulk_create (1)
    # + atomic savepoint'lar — jami kichik o'zgarmas son (obunachi soniga BOG'LIQ EMAS)
    with django_assert_num_queries(6):
        assert notify_new_episode_followers.apply(args=[ep.pk]).result == 20


@pytest.mark.django_db
def test_webhook_ready_queues_fanout(
    client, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.BUNNY_WEBHOOK_SECRET = "wh-secret"
    movie = MovieFactory()
    ep = EpisodeFactory(
        movie=movie, bunny_video_id="guid-777", upload_status=UploadStatus.PROCESSING
    )
    queued = []
    monkeypatch.setattr(
        "drama.tasks.notify_new_episode_followers.delay", lambda pk: queued.append(pk)
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            "/webhooks/bunny/?secret=wh-secret",
            data='{"VideoGuid": "guid-777", "Status": 4}',
            content_type="application/json",
        )
    assert resp.status_code == 200
    ep.refresh_from_db()
    assert ep.upload_status == UploadStatus.READY
    assert queued == [ep.pk]


@pytest.mark.django_db
def test_settings_page_saves_opt_out(client):
    """Sozlamalar sahifasidagi checkbox opt-out'ni saqlaydi [AC-3 UI]."""
    user = UserFactory()
    client.force_login(user)
    assert user.profile.notify_new_episode is True
    resp = client.post(
        reverse("users:settings"),
        {
            "username": user.username,
            "email": user.email,
            "bio": "",
            "telegram_id": "",
            # notify_new_episode YUBORILMAYDI = checkbox olib tashlangan -> False
        },
    )
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.notify_new_episode is False
