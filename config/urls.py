# config/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from core.health import healthz, readyz
from core.monitoring import metrics_view
from core.pwa import manifest, offline, service_worker
from core.telegram_bot import telegram_webhook
from core.twofactor import admin_2fa_verify
from drama.sitemaps import (
    ActorSitemap,
    CategorySitemap,
    GenreSitemap,
    MovieSitemap,
    StaticPagesSitemap,
    VideoSitemap,
)
from drama.views import robots_txt
from drama.webhooks import bunny_webhook

# Sitemap turlarini ro'yxatga olamiz
sitemaps = {
    "movies": MovieSitemap,
    "actors": ActorSitemap,
    "categories": CategorySitemap,
    "genres": GenreSitemap,
    "pages": StaticPagesSitemap,
}

urlpatterns = [
    # 1. Admin va tizim yo'llari
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    # Admin 2FA tasdiqlash [P10-T4] — ataylab /admin/ TASHQARISIDA (redirect-loop yo'q)
    path("admin-2fa/", admin_2fa_verify, name="admin_2fa_verify"),
    # Health / readiness (monitoring + Docker healthcheck)
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    # Prometheus metrikalari [P12-T2] — METRICS_TOKEN yoki staff sessiya bilan
    path("metrics", metrics_view, name="metrics"),
    # 2. Maxsus SEO fayllar
    path("robots.txt", robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        # image namespace'li shablon [P5-T5]: poster/image'li itemlarga <image:image>
        {"sitemaps": sitemaps, "template_name": "sitemaps/sitemap-images.xml"},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path(
        "sitemap-video.xml",
        sitemap,
        {"sitemaps": {"videos": VideoSitemap}, "template_name": "sitemaps/sitemap-video.xml"},
        name="sitemap_video",
    ),
    # 3. App yo'llari (Namespace bilan)
    path("users/", include("users.urls", namespace="users")),
    # allauth — Google OAuth callback yo'llari (/accounts/google/login/...) [P6-T2].
    # Birinchi-tomon login/register MAXSUS (users:) — allauth account view'lariga
    # havola qilinmaydi; faqat socialaccount oqimi ishlatiladi.
    path("accounts/", include("allauth.urls")),
    path("billing/", include("billing.urls")),  # checkout + Payme webhook [P7-T2]
    # 4. REST API (P2)
    path("api/v1/", include("config.api_urls")),
    # 5. Tashqi webhook'lar (P3)
    path("webhooks/bunny/", bunny_webhook, name="bunny_webhook"),
    path("webhooks/telegram/", telegram_webhook, name="telegram_webhook"),
    # PWA [P5-T6] — drama catch-all'dan OLDIN (aks holda "offline/" -> <slug>/ ga tushardi)
    path("manifest.webmanifest", manifest, name="manifest"),
    path("sw.js", service_worker, name="service_worker"),
    path("offline/", offline, name="offline"),
    # Huquqiy sahifalar [P10-T5 qisman] — drama catch-all'dan OLDIN turishi shart
    path("shartlar/", TemplateView.as_view(template_name="pages/terms.html"), name="terms"),
    path(
        "maxfiylik/",
        TemplateView.as_view(template_name="pages/privacy.html"),
        name="privacy",
    ),
    path("", include("drama.urls", namespace="drama")),
    path("funding/", include("funding.urls")),
]

# Media fayllar uchun (Faqat DEBUG rejimida)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # debug-toolbar [P9-T2]: faqat dev'da o'rnatilgan (import-guard)
    try:
        from debug_toolbar.toolbar import debug_toolbar_urls

        urlpatterns += debug_toolbar_urls()
    except ImportError:
        pass

# 404 Xatolik uchun handler
handler404 = "drama.views.error_404"
