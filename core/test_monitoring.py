"""Monitoring testlari [P12-T2] — /metrics himoya, gauge'lar, heartbeat, alertlar."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core import monitoring
from core import tasks as core_tasks
from users.models import TopUpRequest

# --- /metrics himoyasi ---


@pytest.mark.django_db
def test_metrics_forbidden_without_token_or_staff(client, settings):
    settings.METRICS_TOKEN = ""
    assert client.get("/metrics").status_code == 403  # token sozlanmagan + anonim

    settings.METRICS_TOKEN = "s3cr3t"
    assert client.get("/metrics").status_code == 403  # token berilmagan
    assert client.get("/metrics", {"token": "xato"}).status_code == 403


@pytest.mark.django_db
def test_metrics_with_bearer_token(client, settings):
    settings.METRICS_TOKEN = "s3cr3t"
    resp = client.get("/metrics", HTTP_AUTHORIZATION="Bearer s3cr3t")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "drama_up 1" in body
    assert "drama_db_up 1" in body
    assert resp["Content-Type"].startswith("text/plain")


@pytest.mark.django_db
def test_metrics_staff_session_and_gauges(client, settings):
    settings.METRICS_TOKEN = ""
    staff = User.objects.create_superuser("m1", "m@test.uz", "pass12345")
    client.force_login(staff)
    body = client.get("/metrics").content.decode()
    assert "drama_users_total 1" in body
    assert "drama_pending_topups 0" in body
    assert "drama_pending_review_reports 0" in body


# --- heartbeat (dead-man switch) ---


def test_heartbeat_off_without_url(settings, monkeypatch):
    settings.HEARTBEAT_URL = ""
    called = []
    monkeypatch.setattr("requests.get", lambda *a, **k: called.append(a))
    assert core_tasks.heartbeat_task.apply().result == "off"
    assert called == []


def test_heartbeat_pings_configured_url(settings, monkeypatch):
    settings.HEARTBEAT_URL = "https://hc.example/ping/abc"
    called = {}
    monkeypatch.setattr("requests.get", lambda url, timeout: called.setdefault("url", url))
    assert core_tasks.heartbeat_task.apply().result == "ok"
    assert called["url"] == "https://hc.example/ping/abc"


# --- alertlar ---


@pytest.mark.django_db
def test_alerts_sent_once_with_cooldown(monkeypatch):
    cache.clear()
    monkeypatch.setattr(monitoring, "collect_problems", lambda: [("queue", "test xabar")])
    sent = []
    monkeypatch.setattr(core_tasks.notify_telegram_task, "delay", lambda msg: sent.append(msg))

    assert core_tasks.monitoring_alerts_task.apply().result == 1
    assert core_tasks.monitoring_alerts_task.apply().result == 0  # cooldown (1h)
    assert len(sent) == 1
    assert "test xabar" in sent[0]


@pytest.mark.django_db
def test_no_alert_when_all_clear(monkeypatch):
    cache.clear()
    monkeypatch.setattr(monitoring, "collect_problems", lambda: [])
    sent = []
    monkeypatch.setattr(core_tasks.notify_telegram_task, "delay", lambda msg: sent.append(msg))
    assert core_tasks.monitoring_alerts_task.apply().result == 0
    assert sent == []


@pytest.mark.django_db
def test_stale_pending_topup_detected():
    buyer = User.objects.create_user("stale1", "s@test.uz", "pass12345")
    req = TopUpRequest.objects.create(
        user=buyer,
        amount_uzs=10000,
        receipt_image=SimpleUploadedFile("c.jpg", b"fake-image-bytes", "image/jpeg"),
    )
    # auto_now_add'ni chetlab eski sana qo'yamiz (24h chegaradan oshiq)
    TopUpRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(hours=30))
    problems = dict(monitoring.collect_problems())
    assert "stale_topup" in problems

    # yangi (30 daqiqalik) pending esa alert bermaydi
    TopUpRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(minutes=30))
    assert "stale_topup" not in dict(monitoring.collect_problems())
