"""users/test_cabinet.py — foydalanuvchi kabineti [P6-T3].

Bildirishnomalar (model/servis/triggerlar/markaz view'lari) + 'Davom ettirish'
selector va profil bo'limi + nav badge.
"""

from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from drama.factories import EpisodeFactory, MovieFactory
from users.models import Notification, TopUpRequest, WatchProgress
from users.selectors import continue_watching
from users.services import notifications as notif


def _png():
    buf = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buf, "PNG")
    return SimpleUploadedFile("receipt.png", buf.getvalue(), "image/png")


def _user(name="aziz"):
    return User.objects.create_user(name, f"{name}@drama.uz", "parol12345")


# ---- Model / servis ------------------------------------------------------------


@pytest.mark.django_db
def test_notify_creates_notification():
    u = _user()
    n = notif.notify(u, Notification.Kind.SYSTEM, "Salom", body="Xush kelibsiz", url="/x/")
    assert n.pk is not None
    assert Notification.objects.filter(recipient=u, title="Salom", is_read=False).exists()


@pytest.mark.django_db
def test_notify_none_recipient_is_noop():
    assert notif.notify(None, Notification.Kind.SYSTEM, "Hech kim") is None
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_unread_count_and_mark_all_read():
    u = _user()
    for i in range(3):
        notif.notify(u, Notification.Kind.SYSTEM, f"n{i}")
    other = _user("boshqa")
    notif.notify(other, Notification.Kind.SYSTEM, "boshqaga")  # aralashmaydi
    assert notif.unread_count(u) == 3
    assert notif.mark_all_read(u) == 3
    assert notif.unread_count(u) == 0
    assert notif.unread_count(other) == 1  # boshqasi tegilmadi


# ---- Triggerlar ----------------------------------------------------------------


@pytest.mark.django_db
def test_topup_approval_creates_notification():
    u = _user()
    req = TopUpRequest.objects.create(user=u, amount_uzs=5000, receipt_image=_png())
    assert not Notification.objects.filter(recipient=u, kind="topup").exists()  # pending — yo'q
    req.status = "approved"
    req.save()  # approve → ledger kredit + ichki bildirishnoma
    n = Notification.objects.get(recipient=u, kind="topup")
    assert "to'ldirildi" in n.title.lower() or "to`ldirildi" in n.title.lower()
    assert n.url == reverse("users:transactions")


@pytest.mark.django_db
def test_follow_creates_notification(client):
    aziz = _user("aziz")
    bek = _user("bek")
    client.force_login(aziz)
    resp = client.post(reverse("users:follow", args=[bek.username]))
    assert resp.status_code == 302
    n = Notification.objects.get(recipient=bek, kind="follow")
    assert "aziz" in n.body
    assert n.url == reverse("users:profile", args=["aziz"])


@pytest.mark.django_db
def test_repeat_follow_does_not_duplicate_notification(client):
    aziz = _user("aziz")
    bek = _user("bek")
    client.force_login(aziz)
    client.post(reverse("users:follow", args=[bek.username]))
    client.post(reverse("users:follow", args=[bek.username]))  # takror
    assert Notification.objects.filter(recipient=bek, kind="follow").count() == 1


# ---- Bildirishnoma markazi view'lari -------------------------------------------


@pytest.mark.django_db
def test_notifications_view_lists_own_only(client):
    me = _user("me")
    other = _user("other")
    notif.notify(me, Notification.Kind.SYSTEM, "MENIKI")
    notif.notify(other, Notification.Kind.SYSTEM, "BOSHQANIKI")
    client.force_login(me)
    html = client.get(reverse("users:notifications")).content.decode()
    assert "MENIKI" in html
    assert "BOSHQANIKI" not in html  # IDOR: faqat o'z ro'yxati


@pytest.mark.django_db
def test_notifications_view_requires_login(client):
    resp = client.get(reverse("users:notifications"))
    assert resp.status_code == 302  # login_required


@pytest.mark.django_db
def test_mark_notification_read_and_redirects_to_url(client):
    me = _user("me")
    n = notif.notify(me, Notification.Kind.TOPUP, "Coin", url="/users/transactions/")
    client.force_login(me)
    resp = client.post(reverse("users:notification_read", args=[n.pk]))
    assert resp.status_code == 302
    assert resp.url == "/users/transactions/"
    n.refresh_from_db()
    assert n.is_read is True


@pytest.mark.django_db
def test_mark_notification_read_idor_protected(client):
    victim = _user("victim")
    attacker = _user("attacker")
    n = notif.notify(victim, Notification.Kind.SYSTEM, "Maxfiy")
    client.force_login(attacker)
    resp = client.post(reverse("users:notification_read", args=[n.pk]))
    assert resp.status_code == 404  # boshqaning bildirishnomasi topilmaydi
    n.refresh_from_db()
    assert n.is_read is False


@pytest.mark.django_db
def test_mark_all_read_view(client):
    me = _user("me")
    for i in range(4):
        notif.notify(me, Notification.Kind.SYSTEM, f"n{i}")
    client.force_login(me)
    resp = client.post(reverse("users:notifications_read_all"))
    assert resp.status_code == 302
    assert notif.unread_count(me) == 0


# ---- 'Davom ettirish' selector + profil bo'limi --------------------------------


@pytest.mark.django_db
def test_continue_watching_selector_excludes_completed_and_orders():
    u = _user()
    movie = MovieFactory()
    ep1 = EpisodeFactory(movie=movie, episode_number=1)
    ep2 = EpisodeFactory(movie=movie, episode_number=2)
    ep3 = EpisodeFactory(movie=movie, episode_number=3)
    WatchProgress.objects.create(
        user=u, episode=ep1, position_seconds=10, duration_seconds=100, completed=True
    )
    wp2 = WatchProgress.objects.create(
        user=u, episode=ep2, position_seconds=20, duration_seconds=100
    )
    wp3 = WatchProgress.objects.create(
        user=u, episode=ep3, position_seconds=30, duration_seconds=100
    )
    wp2.position_seconds = 25
    wp2.save()  # updated_at yangilanadi -> wp2 eng so'nggi bo'ladi
    result = list(continue_watching(u))
    assert [r.pk for r in result] == [wp2.pk, wp3.pk]  # -updated_at, tugatilgan (ep1) chiqmaydi


@pytest.mark.django_db
def test_profile_shows_continue_watching_for_owner(client):
    u = _user("owner")
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=1)
    WatchProgress.objects.create(user=u, episode=ep, position_seconds=30, duration_seconds=100)
    client.force_login(u)
    html = client.get(reverse("users:profile", args=[u.username])).content.decode()
    # continue-watching kartasi render bo'ladi. movie.title FAQAT shu bo'limda chiqadi
    # (bu profilda UserMovieList yo'q -> 'Oxirgi harakatlar' bo'sh) = ishonchli signal.
    assert movie.title in html


@pytest.mark.django_db
def test_profile_hides_continue_watching_from_other_viewers(client):
    owner = _user("owner")
    viewer = _user("viewer")
    movie = MovieFactory()
    ep = EpisodeFactory(movie=movie, episode_number=1)
    WatchProgress.objects.create(user=owner, episode=ep, position_seconds=30, duration_seconds=100)
    client.force_login(viewer)
    html = client.get(reverse("users:profile", args=[owner.username])).content.decode()
    # boshqa foydalanuvchiga continue_watching konteksti None -> karta (movie.title) yo'q
    assert movie.title not in html


@pytest.mark.django_db
def test_context_processor_gated_by_auth():
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from users.context_processors import notifications as cp

    u = _user()
    notif.notify(u, Notification.Kind.SYSTEM, "x")
    req = RequestFactory().get("/")
    req.user = AnonymousUser()
    assert cp(req) == {}  # anonim: BO'SH (so'rov yo'q -> P9-T2 query-count testlari xavfsiz)
    req.user = u
    assert cp(req) == {"notifications_unread": 1}


@pytest.mark.django_db
def test_nav_bell_authenticated_only(client):
    assert 'aria-label="Bildirishnomalar"' not in client.get("/").content.decode()
    u = _user()
    client.force_login(u)
    assert 'aria-label="Bildirishnomalar"' in client.get("/").content.decode()
