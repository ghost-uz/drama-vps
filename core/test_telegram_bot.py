"""V2A-T2 testlari — bot bog'lash, buyruqlar, webhook secret, push 403 [API mock]."""

import json

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse

from core import telegram_bot
from core.tasks import send_telegram_push_task
from drama.factories import EpisodeFactory, MovieFactory
from drama.tasks import notify_new_episode_followers
from users.factories import UserFactory
from users.models import Profile, UserMovieList


@pytest.fixture
def outbox(monkeypatch):
    """send_message'ni yig'uvchi bilan almashtiradi — API'ga chiqmaymiz."""
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        telegram_bot, "send_message", lambda chat_id, text: sent.append((chat_id, text))
    )
    return sent


def _update(chat_id, text):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


# --- Deep-link bog'lash [AC-1] ---


@pytest.mark.django_db
def test_link_flow_end_to_end(client, settings, outbox):
    settings.TELEGRAM_BOT_USERNAME = "drama_test_bot"
    cache.clear()
    user = UserFactory()
    client.force_login(user)

    resp = client.post(reverse("users:telegram_bot_link"))
    assert resp.status_code == 302
    assert resp["Location"].startswith("https://t.me/drama_test_bot?start=")
    token = resp["Location"].split("start=")[1]

    assert telegram_bot.handle_update(_update(555, f"/start {token}")) == "linked"
    profile = Profile.objects.get(user=user)
    assert profile.telegram_chat_id == 555
    assert profile.notify_new_episode_telegram is True
    assert "ulandi" in outbox[-1][1]

    # BIR MARTALIK: o'sha token qayta ishlamaydi
    assert telegram_bot.handle_update(_update(999, f"/start {token}")) == "link_expired"
    assert not Profile.objects.filter(telegram_chat_id=999).exists()


@pytest.mark.django_db
def test_link_token_expired(outbox):
    cache.clear()
    assert telegram_bot.handle_update(_update(555, "/start yoq-token")) == "link_expired"


@pytest.mark.django_db
def test_link_conflict_other_account(outbox):
    cache.clear()
    first = UserFactory()
    Profile.objects.filter(user=first).update(telegram_chat_id=777)
    second = UserFactory()
    token = telegram_bot.make_link_token(second.id)

    assert telegram_bot.handle_update(_update(777, f"/start {token}")) == "link_conflict"
    second.profile.refresh_from_db()
    assert second.profile.telegram_chat_id is None
    first.profile.refresh_from_db()
    assert first.profile.telegram_chat_id == 777  # birinchisi buzilmadi


# --- Buyruqlar ---


@pytest.mark.django_db
def test_stop_and_restart_toggle(outbox):
    user = UserFactory()
    Profile.objects.filter(user=user).update(telegram_chat_id=555)

    assert telegram_bot.handle_update(_update(555, "/stop")) == "stopped"
    user.profile.refresh_from_db()
    assert user.profile.notify_new_episode_telegram is False
    assert user.profile.telegram_chat_id == 555  # ulanish saqlanadi

    assert telegram_bot.handle_update(_update(555, "/start")) == "already_linked"
    user.profile.refresh_from_db()
    assert user.profile.notify_new_episode_telegram is True


@pytest.mark.django_db
def test_search_command(settings, outbox):
    settings.SITE_URL = "https://drama.test"
    movie = MovieFactory(title="Vinchenzo qasosi")
    assert telegram_bot.handle_update(_update(1, "/search Vinchenzo")) == "search_ok"
    text = outbox[-1][1]
    assert "Vinchenzo qasosi" in text
    assert f"https://drama.test{movie.get_absolute_url()}" in text

    assert telegram_bot.handle_update(_update(1, "/search v")) == "search_short"
    assert telegram_bot.handle_update(_update(1, "/search yo'qnarsa")) == "search_empty"


# --- Webhook secret [AC-4] ---


@pytest.mark.django_db
def test_webhook_secret_enforced(client, settings, outbox):
    settings.TELEGRAM_WEBHOOK_SECRET = "wh-s3cret"
    body = json.dumps(_update(1, "/start"))

    resp = client.post("/webhooks/telegram/", body, content_type="application/json")
    assert resp.status_code == 403  # header yo'q
    resp = client.post(
        "/webhooks/telegram/",
        body,
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "xato"},
    )
    assert resp.status_code == 403
    resp = client.post(  # non-ASCII header 500 emas, 403 (bytes compare_digest)
        "/webhooks/telegram/",
        body,
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "xato-é"},
    )
    assert resp.status_code == 403

    resp = client.post(
        "/webhooks/telegram/",
        body,
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wh-s3cret"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "start_unlinked"


@pytest.mark.django_db
def test_webhook_secret_unset_means_closed(client, settings):
    settings.TELEGRAM_WEBHOOK_SECRET = ""
    resp = client.post("/webhooks/telegram/", "{}", content_type="application/json")
    assert resp.status_code == 403


# --- Push va 403 [AC-2, AC-3] ---


@pytest.mark.django_db
def test_push_403_unlinks_channel(monkeypatch):
    user = UserFactory()
    Profile.objects.filter(user=user).update(telegram_chat_id=555)

    def blocked(chat_id, text):
        raise telegram_bot.TelegramBlocked("blok")

    monkeypatch.setattr(telegram_bot, "send_message", blocked)
    result = send_telegram_push_task.apply(args=[555, "salom"])
    assert result.successful()  # xato tashqariga otilmaydi, LOG'lanadi
    user.profile.refresh_from_db()
    assert user.profile.telegram_chat_id is None  # kanal o'chirildi


def test_push_network_error_retries(monkeypatch):
    from celery.exceptions import Retry

    def down(chat_id, text):
        raise requests.ConnectionError("tarmoq yo'q")

    monkeypatch.setattr(telegram_bot, "send_message", down)
    # 403'dan farqli: tarmoq xatosi RETRY'ga olib keladi (eager rejimda Retry otiladi)
    with pytest.raises(Retry):
        send_telegram_push_task.apply(args=[555, "salom"], throw=True)


@pytest.mark.django_db
def test_fanout_queues_telegram_push(settings, monkeypatch, django_capture_on_commit_callbacks):
    """V2A-T1 fan-out endi ulangan userlarga bot-push ham navbatlaydi [AC-2]."""
    settings.SITE_URL = "https://drama.test"
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=12)

    linked = UserFactory()
    Profile.objects.filter(user=linked).update(telegram_chat_id=888)
    UserMovieList.objects.create(profile=linked.profile, movie=movie, status=UserMovieList.WATCHING)
    unlinked = UserFactory()
    UserMovieList.objects.create(
        profile=unlinked.profile, movie=movie, status=UserMovieList.WATCHING
    )

    pushed = []
    monkeypatch.setattr(
        "core.tasks.send_telegram_push_task.delay",
        lambda chat_id, text: pushed.append((chat_id, text)),
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert notify_new_episode_followers.apply(args=[ep.pk]).result == 2  # in-app 2 ta

    assert len(pushed) == 1  # bot-push faqat ulanganga
    chat_id, text = pushed[0]
    assert chat_id == 888
    assert movie.title in text
    assert "12-qism" in text
    assert f"https://drama.test{movie.get_absolute_url()}?episode=12" in text
