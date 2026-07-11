"""Izoh moderatsiyasi testlari [P14-T3] — report, navbat, avto-yashirish, rate-limit."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from drama.factories import MovieFactory
from drama.models import Review, ReviewReport
from users.factories import UserFactory


def _review(movie=None, text="Oddiy izoh", **kwargs):
    movie = movie or MovieFactory()
    return Review.objects.create(user=UserFactory(), movie=movie, text=text, **kwargs)


# --- report oqimi ---


@pytest.mark.django_db
def test_report_creates_pending_entry(client):
    review = _review()
    reporter = UserFactory()
    client.force_login(reporter)
    resp = client.post(reverse("drama:report_review", args=[review.pk]), {"reason": "spam"})
    assert resp.status_code == 302
    report = ReviewReport.objects.get()
    assert report.review == review
    assert report.reporter == reporter
    assert report.reason == ReviewReport.Reason.SPAM
    assert report.status == ReviewReport.Status.PENDING


@pytest.mark.django_db
def test_report_requires_auth(client):
    review = _review()
    resp = client.post(reverse("drama:report_review", args=[review.pk]), {"reason": "spam"})
    assert resp.status_code == 401
    assert ReviewReport.objects.count() == 0


@pytest.mark.django_db
def test_report_duplicate_is_single_row(client):
    """Takror report yangi yozuv ochmaydi; HTMX javobi 'allaqachon' deydi."""
    review = _review()
    client.force_login(UserFactory())
    url = reverse("drama:report_review", args=[review.pk])
    client.post(url, {"reason": "spam"})
    resp = client.post(url, {"reason": "abuse"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert "Allaqachon yuborilgan" in resp.content.decode()
    assert ReviewReport.objects.count() == 1
    assert ReviewReport.objects.get().reason == ReviewReport.Reason.SPAM  # birinchisi qoladi


@pytest.mark.django_db
def test_report_invalid_reason_falls_back_to_other(client):
    review = _review()
    client.force_login(UserFactory())
    client.post(reverse("drama:report_review", args=[review.pk]), {"reason": "hack"})
    assert ReviewReport.objects.get().reason == ReviewReport.Reason.OTHER


@pytest.mark.django_db
def test_report_htmx_returns_confirmation(client):
    review = _review()
    client.force_login(UserFactory())
    resp = client.post(
        reverse("drama:report_review", args=[review.pk]),
        {"reason": "spam"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert "Shikoyat yuborildi" in resp.content.decode()


# --- avto-yashirish (filtr) ---


@pytest.mark.django_db
def test_auto_hide_after_threshold_and_excluded_from_list(client):
    """N ta ochiq shikoyat -> izoh avto-yashiriladi va ro'yxatdan yo'qoladi."""
    review = _review(text="Juda yomon spam matni")
    url = reverse("drama:report_review", args=[review.pk])
    for _ in range(ReviewReport.AUTO_HIDE_THRESHOLD):
        client.force_login(UserFactory())
        client.post(url, {"reason": "spam"})
    review.refresh_from_db()
    assert review.is_hidden is True

    client.logout()
    resp = client.get(reverse("drama:movie_reviews", args=[review.movie.slug]))
    assert resp.status_code == 200
    assert "Juda yomon spam matni" not in resp.content.decode()


@pytest.mark.django_db
def test_hidden_reply_excluded_from_list(client):
    root = _review(text="Root izoh matni")
    Review.objects.create(
        user=UserFactory(),
        movie=root.movie,
        parent=root,
        text="Yashirin javob matni",
        is_hidden=True,
    )
    resp = client.get(reverse("drama:movie_reviews", args=[root.movie.slug]))
    body = resp.content.decode()
    assert "Root izoh matni" in body
    assert "Yashirin javob matni" not in body


# --- rate-limit (abuse himoyasi) ---


@pytest.mark.django_db
def test_report_rate_limited_429(client, settings):
    from django.core.cache import cache

    cache.clear()
    settings.RATELIMIT_RATES = {**settings.RATELIMIT_RATES, "report": "3/h"}
    movie = MovieFactory()
    client.force_login(UserFactory())
    reviews = [_review(movie=movie) for _ in range(4)]
    for r in reviews[:3]:
        resp = client.post(reverse("drama:report_review", args=[r.pk]), {"reason": "spam"})
        assert resp.status_code == 302
    resp = client.post(reverse("drama:report_review", args=[reviews[3].pk]), {"reason": "spam"})
    assert resp.status_code == 429


# --- admin navbati ---


@pytest.mark.django_db
def test_admin_accept_action_hides_review_and_resolves_reports(client):
    review = _review()
    report = ReviewReport.objects.create(review=review, reporter=UserFactory())
    other = ReviewReport.objects.create(review=review, reporter=UserFactory())
    client.force_login(User.objects.create_superuser("mod", "m@test.uz", "pass12345"))
    resp = client.post(
        reverse("admin:drama_reviewreport_changelist"),
        {"action": "accept_and_hide", "_selected_action": [str(report.pk)]},
    )
    assert resp.status_code == 302
    review.refresh_from_db()
    report.refresh_from_db()
    other.refresh_from_db()
    assert review.is_hidden is True
    assert report.status == ReviewReport.Status.ACCEPTED
    # o'sha izohning boshqa ochiq shikoyati ham yopiladi — navbat toza
    assert other.status == ReviewReport.Status.ACCEPTED


@pytest.mark.django_db
def test_admin_reject_action_reopens_auto_hidden_review(client):
    review = _review()
    reports = [ReviewReport.objects.create(review=review, reporter=UserFactory()) for _ in range(3)]
    review.is_hidden = True
    review.save(update_fields=["is_hidden"])
    client.force_login(User.objects.create_superuser("mod2", "m2@test.uz", "pass12345"))
    resp = client.post(
        reverse("admin:drama_reviewreport_changelist"),
        {"action": "reject_reports", "_selected_action": [str(r.pk) for r in reports]},
    )
    assert resp.status_code == 302
    review.refresh_from_db()
    assert review.is_hidden is False  # asossiz avto-yashirish qaytarildi
    assert set(ReviewReport.objects.values_list("status", flat=True)) == {
        ReviewReport.Status.REJECTED
    }
