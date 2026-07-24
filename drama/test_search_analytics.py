"""Qidiruv analitikasi testlari [V2G-T3] — log yozish, normalizatsiya, retention, hisobot.

Test muhitida CELERY_TASK_ALWAYS_EAGER=True -> `.delay()` sinxron ishlaydi,
shu bois log qatorlarini to'g'ridan-to'g'ri tekshiramiz.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from drama.factories import MovieFactory
from drama.models import SearchQueryLog
from drama.tasks import cleanup_old_search_logs, log_search_query


# ---------------------------------------------------------------------------
# Normalizatsiya
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Vincenzo", "vincenzo"),
        ("  VINCENZO  ", "vincenzo"),
        ("Ko'p   bo'shliq", "ko'p bo'shliq"),
        ("MiXeD CaSe", "mixed case"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize(raw, expected):
    assert SearchQueryLog.normalize(raw) == expected


@pytest.mark.django_db
def test_normalize_merges_variants():
    """'Vincenzo', ' vincenzo ', 'VINCENZO' bitta normalized so'rovga birlashadi."""
    for raw in ("Vincenzo", " vincenzo ", "VINCENZO"):
        log_search_query(raw, 3, None)
    assert SearchQueryLog.objects.filter(query="vincenzo").count() == 3
    assert SearchQueryLog.objects.values("query").distinct().count() == 1


# ---------------------------------------------------------------------------
# Log yozish task'i
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_log_task_writes_row():
    log_search_query("Reply 1988", 5, None)
    log = SearchQueryLog.objects.get()
    assert log.query == "reply 1988"
    assert log.results_count == 5
    assert log.user is None


@pytest.mark.django_db
def test_log_task_skips_empty_normalized():
    log_search_query("   ", 0, None)
    assert SearchQueryLog.objects.count() == 0


@pytest.mark.django_db
def test_log_task_records_user():
    u = User.objects.create_user("searcher")
    log_search_query("Goblin", 2, u.id)
    assert SearchQueryLog.objects.get().user_id == u.id


# ---------------------------------------------------------------------------
# View integratsiyasi (eager delay)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_live_search_logs_query(client):
    MovieFactory(title="Vincenzo")
    client.get(reverse("drama:live_search"), {"q": "Vincenzo"})
    log = SearchQueryLog.objects.get()
    assert log.query == "vincenzo"
    assert log.results_count >= 1


@pytest.mark.django_db
def test_live_search_zero_result_logged(client):
    client.get(reverse("drama:live_search"), {"q": "yoqmagannarsa"})
    log = SearchQueryLog.objects.get()
    assert log.query == "yoqmagannarsa"
    assert log.results_count == 0


@pytest.mark.django_db
def test_live_search_too_short_not_logged(client):
    client.get(reverse("drama:live_search"), {"q": "a"})
    assert SearchQueryLog.objects.count() == 0


@pytest.mark.django_db
def test_search_view_logs_first_page_only(client):
    MovieFactory(title="Crash Landing")
    client.get(reverse("drama:search"), {"q": "Crash"})
    assert SearchQueryLog.objects.filter(query="crash").count() == 1
    # 2-sahifa (cheksiz-skroll) qayta LOG QILMAYDI
    client.get(reverse("drama:search"), {"q": "Crash", "page": "2"})
    assert SearchQueryLog.objects.filter(query="crash").count() == 1


@pytest.mark.django_db
def test_logging_failure_never_breaks_search(client, monkeypatch):
    """Broker o'chiq bo'lsa ham qidiruv 200 qaytaradi (best-effort logging)."""

    def boom(*a, **k):
        raise RuntimeError("broker down")

    monkeypatch.setattr("drama.tasks.log_search_query.delay", boom)
    resp = client.get(reverse("drama:live_search"), {"q": "Vincenzo"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Retention task
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_cleanup_deletes_old_logs():
    old = SearchQueryLog.objects.create(query="eski", results_count=0)
    SearchQueryLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
    SearchQueryLog.objects.create(query="yangi", results_count=0)  # bugungi

    deleted = cleanup_old_search_logs(days=90)
    assert deleted == 1
    assert list(SearchQueryLog.objects.values_list("query", flat=True)) == ["yangi"]


# ---------------------------------------------------------------------------
# Admin hisobot
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_admin_report_top_and_zero(client):
    admin = User.objects.create_superuser("boss", "b@x.uz", "pw")
    client.force_login(admin)

    for _ in range(3):
        log_search_query("mashhur", 5, None)  # top (natijali)
    for _ in range(2):
        log_search_query("yoqnarsa", 0, None)  # natijasiz
    log_search_query("boshqa", 1, None)

    url = reverse("admin:drama_searchquerylog_report_view")
    resp = client.get(url, {"days": 30})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "mashhur" in body
    assert "yoqnarsa" in body
    # Kontekstda to'g'ri aggregatsiya
    top = {r["query"]: r["n"] for r in resp.context["top"]}
    zero = {r["query"]: r["n"] for r in resp.context["zero"]}
    assert top["mashhur"] == 3
    assert zero == {"yoqnarsa": 2}


@pytest.mark.django_db
def test_admin_report_period_filter(client):
    admin = User.objects.create_superuser("boss2", "b2@x.uz", "pw")
    client.force_login(admin)

    old = SearchQueryLog.objects.create(query="eskiq", results_count=0)
    SearchQueryLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
    log_search_query("yangiq", 0, None)

    url = reverse("admin:drama_searchquerylog_report_view")
    # 7 kunlik davr -> eski so'rov chiqmaydi
    resp = client.get(url, {"days": 7})
    zero = {r["query"] for r in resp.context["zero"]}
    assert "yangiq" in zero
    assert "eskiq" not in zero
    # 90 kun -> ikkalasi ham
    resp90 = client.get(url, {"days": 90})
    zero90 = {r["query"] for r in resp90.context["zero"]}
    assert {"yangiq", "eskiq"} <= zero90


@pytest.mark.django_db
def test_admin_report_requires_permission(client):
    """Oddiy staff (perm'siz) hisobotga kira olmaydi."""
    staff = User.objects.create_user("staff", password="pw", is_staff=True)
    client.force_login(staff)
    resp = client.get(reverse("admin:drama_searchquerylog_report_view"))
    assert resp.status_code in (403, 302)


@pytest.mark.django_db
def test_log_not_editable_in_admin():
    from drama.admin import SearchQueryLogAdmin

    a = SearchQueryLogAdmin(SearchQueryLog, None)
    assert a.has_add_permission(None) is False
    assert a.has_change_permission(None) is False
