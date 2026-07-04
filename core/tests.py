"""core notifications/tasks testlari [P3-T3]."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core import mail

from core.tasks import notify_telegram_task, send_email_task


def test_send_telegram_unconfigured_skips(settings):
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.TELEGRAM_ADMIN_CHAT_ID = ""
    from core.notifications import send_telegram

    assert send_telegram("test") is False


def test_send_telegram_configured_posts(settings):
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_ADMIN_CHAT_ID = "123"
    from core.notifications import send_telegram

    with patch("core.notifications.requests.post") as mock_post:
        mock_post.return_value.raise_for_status = lambda: None
        assert send_telegram("salom") is True
        mock_post.assert_called_once()


@pytest.mark.django_db
def test_send_email_task_delivers(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox.clear()
    send_email_task("Subj", "Body", ["u@example.com"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Subj"


@pytest.mark.django_db
def test_notify_telegram_task_calls_send(settings):
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_ADMIN_CHAT_ID = "123"
    with patch("core.notifications.send_telegram") as mock_send:
        notify_telegram_task("hi")
    mock_send.assert_called_once_with("hi")


@pytest.mark.django_db
def test_topup_approve_sends_user_email(django_capture_on_commit_callbacks):
    from users.models import TopUpRequest

    user = User.objects.create_user(username="tu", password="pass12345", email="tu@example.com")
    topup = TopUpRequest.objects.create(user=user, amount_uzs=10000, status="pending")
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        topup.status = "approved"
        topup.save()  # approve -> wallet.credit + email (on_commit)
    assert len(mail.outbox) == 1
    assert "tu@example.com" in mail.outbox[0].to


@pytest.mark.django_db
def test_topup_approve_no_email_when_user_has_none(django_capture_on_commit_callbacks):
    from users.models import TopUpRequest

    user = User.objects.create_user(username="noemail", password="pass12345", email="")
    topup = TopUpRequest.objects.create(user=user, amount_uzs=5000, status="pending")
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        topup.status = "approved"
        topup.save()
    assert len(mail.outbox) == 0  # email yo'q -> yuborilmaydi


# --- P3-T4: davriy beat tasklar ---


@pytest.mark.django_db
def test_expire_premium():
    from datetime import timedelta

    from django.utils import timezone

    from users.tasks import expire_premium

    expired = User.objects.create_user("exp", password="pass12345")
    expired.profile.is_premium = True
    expired.profile.premium_until = timezone.now() - timedelta(days=1)
    expired.profile.save()

    active = User.objects.create_user("act", password="pass12345")
    active.profile.is_premium = True
    active.profile.premium_until = timezone.now() + timedelta(days=10)
    active.profile.save()

    assert expire_premium() == 1
    expired.profile.refresh_from_db()
    active.profile.refresh_from_db()
    assert expired.profile.is_premium is False
    assert active.profile.is_premium is True  # muddati o'tmagan — tegilmaydi


@pytest.mark.django_db
def test_cleanup_stale_topups():
    from datetime import timedelta

    from django.utils import timezone

    from users.models import TopUpRequest
    from users.tasks import cleanup_stale_topups

    user = User.objects.create_user("tp", password="pass12345")
    old = TopUpRequest.objects.create(user=user, amount_uzs=10000, status="pending")
    TopUpRequest.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))
    new = TopUpRequest.objects.create(user=user, amount_uzs=5000, status="pending")

    assert cleanup_stale_topups() == 1
    old.refresh_from_db()
    new.refresh_from_db()
    assert old.status == "rejected"
    assert new.status == "pending"  # yangi — tegilmaydi


@pytest.mark.django_db
def test_recompute_trending_tags():
    from django.core.cache import cache
    from django.core.files.uploadedfile import SimpleUploadedFile

    from drama.models import Movie, Tag
    from drama.tasks import recompute_trending_tags

    cache.delete("trending_tags")
    tag = Tag.objects.create(name="Drama", slug="drama")
    movie = Movie.objects.create(
        title="M",
        description="x",
        country="KR",
        poster=SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg"),
    )
    movie.tags.add(tag)
    # M2M fix: 'tags' endi modeltranslation'siz -> Count("movies") to'g'ri ishlaydi
    count = recompute_trending_tags()
    assert count == 1
    cached = cache.get("trending_tags")
    assert cached is not None and len(cached) == 1


# --- P10-T1: xavfsizlik headerlari (config/middleware.SecurityHeadersMiddleware) ---


def test_csp_frame_ancestors_allowlist(client):
    """ALLOWALL o'rniga aniq allowlist: o'zimiz + Telegram Web (Mini App iframe)."""
    resp = client.get("/healthz")
    csp = resp["Content-Security-Policy"]
    assert "frame-ancestors 'self' https://web.telegram.org" in csp
    assert "default-src 'self';" in csp


def test_csp_no_unsafe_eval(client):
    """hx-on addEventListener'ga almashtirilgach eval'ga ehtiyoj qolmadi."""
    csp = client.get("/healthz")["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp


def test_x_frame_options_not_allowall(client):
    """Nostandart ALLOWALL (brauzer e'tiborsiz qoldirardi) endi yo'q."""
    resp = client.get("/healthz")
    assert resp["X-Frame-Options"].upper() in {"DENY", "SAMEORIGIN"}


def test_security_headers_modernized(client):
    resp = client.get("/healthz")
    assert "X-XSS-Protection" not in resp  # deprecated — ataylab yuborilmaydi
    assert resp["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp["Permissions-Policy"].startswith("camera=()")
    assert resp["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"


# --- P5-T1: frontend build (Tailwind production + vendorlangan Alpine/htmx) ---


def test_no_play_cdn_or_unpkg_in_templates():
    """Play CDN (dev-vosita!) va unpkg prod shablonlardan butunlay chiqarilgan."""
    from pathlib import Path

    from django.conf import settings

    for html in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        assert "cdn.tailwindcss.com" not in text, html.name
        assert "unpkg.com" not in text, html.name


def test_csp_dropped_unused_script_hosts(client):
    """Endi ishlatilmaydigan hostlar CSP script-src'dan olib tashlangan."""
    csp = client.get("/healthz")["Content-Security-Policy"]
    assert "unpkg.com" not in csp
    assert "cdn.tailwindcss.com" not in csp


def test_vendored_assets_exist():
    from django.contrib.staticfiles import finders

    assert finders.find("css/output.css")
    assert finders.find("js/app.js")
    assert finders.find("js/vendor/alpine-csp.min.js")
    assert finders.find("js/vendor/htmx.min.js")


@pytest.mark.django_db
def test_index_uses_built_assets(client):
    """Bosh sahifa build qilingan CSS + vendorlangan JS'ni ishlatadi (CDN emas)."""
    html = client.get("/").content.decode()
    assert "css/output.css" in html
    assert "js/vendor/alpine-csp.min.js" in html
    assert "js/vendor/htmx.min.js" in html
    assert 'x-data="searchBar"' in html  # Alpine komponenti ulangan
