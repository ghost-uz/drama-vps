"""core/monitoring.py — metrikalar va kritik-alert tekshiruvlari [P12-T2].

Dizayn qarori: per-request hisoblagich YO'Q — gunicorn ko'p-worker rejimida
har worker o'z xotirasida alohida sanaydi (jami noto'g'ri chiqadi);
django-prometheus buni multiproc-dir bilan hal qiladi, biz esa RAD etdik:
request-rate'ni nginx/Cloudflare allaqachon beradi. Bu modul scrape paytida
DB/Redis'dan O'QILADIGAN biznes-gauge'lar va shu manbalardan alert shartlari
(monitoring_alerts_task shularni Telegram'ga chiqaradi).

/metrics himoyasi: METRICS_TOKEN (Authorization: Bearer yoki ?token=) yoki
staff sessiya. Token sozlanmagan bo'lsa tashqi kirish YOPIQ (xavfsiz default).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import redis as redis_lib
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache

logger = logging.getLogger(__name__)

STALE_TOPUP_HOURS = 24  # shundan eski pending topup — admin e'tiboridan chetda
STALE_REPORT_HOURS = 48  # shundan eski pending shikoyat — moderatsiya qotgan


def queue_length() -> int | None:
    """Celery default navbatining uzunligi (Redis broker LLEN); broker o'chiq -> None."""
    try:
        conn = redis_lib.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=3)
        return int(conn.llen("celery"))
    except Exception:
        return None


def _db_up() -> bool:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


def _cache_up() -> bool:
    try:
        cache.set("metrics:probe", "1", 5)
        return cache.get("metrics:probe") == "1"
    except Exception:
        return False


def collect_gauges() -> dict[str, int]:
    """Prometheus gauge'lari — har scrape'da yangidan o'qiladi (arzon COUNT'lar)."""
    from django.contrib.auth.models import User

    from drama.models import Movie, ReviewReport
    from funding.models import FundingProject
    from users.models import CryptoTopUpRequest, TopUpRequest

    pending_topups = (
        TopUpRequest.objects.filter(status="pending").count()
        + CryptoTopUpRequest.objects.filter(status="pending").count()
    )
    gauges: dict[str, int] = {
        "drama_up": 1,
        "drama_db_up": int(_db_up()),
        "drama_cache_up": int(_cache_up()),
        "drama_users_total": User.objects.count(),
        "drama_movies_published_total": Movie.objects.filter(status=Movie.Status.PUBLISHED).count(),
        "drama_pending_topups": pending_topups,
        "drama_pending_review_reports": ReviewReport.objects.filter(
            status=ReviewReport.Status.PENDING
        ).count(),
        "drama_active_funding_projects": FundingProject.objects.filter(
            status=FundingProject.Status.FUNDING
        ).count(),
    }
    qlen = queue_length()
    if qlen is not None:
        gauges["drama_celery_queue_length"] = qlen
    return gauges


def collect_problems() -> list[tuple[str, str]]:
    """(kalit, xabar) ro'yxati — kalit alert-cooldown keshi uchun ishlatiladi."""
    problems: list[tuple[str, str]] = []

    qlen = queue_length()
    threshold = settings.MONITORING_QUEUE_ALERT_THRESHOLD
    if qlen is not None and qlen > threshold:
        problems.append(
            (
                "queue",
                f"Celery navbatida {qlen} task (chegara {threshold}) — "
                "worker qotgan bo'lishi mumkin",
            )
        )

    from users.models import CryptoTopUpRequest, TopUpRequest

    stale_cutoff = timezone.now() - timedelta(hours=STALE_TOPUP_HOURS)
    stale_topups = (
        TopUpRequest.objects.filter(status="pending", created_at__lt=stale_cutoff).count()
        + CryptoTopUpRequest.objects.filter(status="pending", created_at__lt=stale_cutoff).count()
    )
    if stale_topups:
        problems.append(
            (
                "stale_topup",
                f"{stale_topups} ta topup {STALE_TOPUP_HOURS}+ soat kutmoqda — tasdiqlash kerak",
            )
        )

    from drama.models import ReviewReport

    report_cutoff = timezone.now() - timedelta(hours=STALE_REPORT_HOURS)
    stale_reports = ReviewReport.objects.filter(
        status=ReviewReport.Status.PENDING, created_at__lt=report_cutoff
    ).count()
    if stale_reports:
        problems.append(
            (
                "stale_report",
                f"{stale_reports} ta izoh-shikoyat {STALE_REPORT_HOURS}+ soat navbatda",
            )
        )

    if not _cache_up():
        problems.append(("cache", "Redis kesh javob bermayapti"))

    return problems


def _authorized(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return True
    token = settings.METRICS_TOKEN
    if not token:
        return False
    supplied = request.headers.get("Authorization", "")
    supplied = supplied[7:] if supplied.startswith("Bearer ") else request.GET.get("token", "")
    return constant_time_compare(supplied, token)


@never_cache
def metrics_view(request: HttpRequest) -> HttpResponse:
    """GET /metrics — Prometheus text format (0.0.4)."""
    if not _authorized(request):
        return HttpResponse("forbidden", status=403, content_type="text/plain")
    lines = [f"{name} {value}" for name, value in collect_gauges().items()]
    return HttpResponse(
        "\n".join(lines) + "\n",
        content_type="text/plain; version=0.0.4; charset=utf-8",
    )
