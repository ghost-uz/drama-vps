# config/urls.py
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from blog.sitemaps import PostSitemap
from core.agent_discovery import agent_index
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
    "blog": PostSitemap,  # [V2G-T2]
}

# ---------------------------------------------------------------------------
# 1-BLOK — TIL-NEYTRAL yo'llar (i18n_patterns'dan TASHQARIDA) [V2G-T1]
#
# Bu yerdagi URL'lar hech qachon `/en/` prefiksini olmaydi, chunki:
#   • Tashqi tizimlarda QAYD ETILGAN: Bunny/Telegram webhook, Payme merchant
#     endpoint (billing ichida), Search Console sitemap, DNS-AID agent-index.
#     reverse() `/en/` faol paytda prefiks qo'shsa — tashqi chaqiruv sinadi.
#   • Service worker `/sw.js` ILDIZ scope'da bo'lishi SHART; `/offline/` esa
#     SW keshida qat'iy nom bilan yotadi (prefiks kesh-kalitni buzardi).
#   • Infratuzilma (healthz/readyz/metrics), admin va set_language — til-neytral.
#
# ⚠️ allauth (`accounts/`) ATAYLAB shu blokda: allauth OAuth `redirect_uri`ni
#    reverse() bilan quradi. `/en/` faol bo'lsa u `/en/accounts/google/login/
#    callback/` chiqaradi — Google konsolida qayd etilgan URL bilan mos kelmaydi
#    va oqim `redirect_uri_mismatch` bilan yiqiladi.
# ---------------------------------------------------------------------------
urlpatterns = [
    # 1. Admin va tizim yo'llari
    path("admin/", admin.site.urls),
    # set_language view — i18n_patterns ICHIDA BO'LMASLIGI kerak (o'zi til
    # almashtiradi; prefiksli variantda POST target tilga bog'lanib qolardi).
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
    # Agent-discovery indeksi [DNS-AID] — `_index._agents.drama.uz` SVCB yozuvi shu
    # hostga ishora qiladi; agentlar bu yerdan mashina-o'qiydigan API xaritasini oladi.
    path(".well-known/agent-index.json", agent_index, name="agent_index"),
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
    # allauth — Google OAuth callback yo'llari (/accounts/google/login/...) [P6-T2].
    # Birinchi-tomon login/register MAXSUS (users:) — allauth account view'lariga
    # havola qilinmaydi; faqat socialaccount oqimi ishlatiladi.
    path("accounts/", include("allauth.urls")),
    # 3. REST API (P2)
    path("api/v1/", include("config.api_urls")),
    # 4. Tashqi webhook'lar (P3)
    path("webhooks/bunny/", bunny_webhook, name="bunny_webhook"),
    path("webhooks/telegram/", telegram_webhook, name="telegram_webhook"),
    # PWA [P5-T6] — drama catch-all'dan OLDIN (aks holda "offline/" -> <slug>/ ga tushardi)
    path("manifest.webmanifest", manifest, name="manifest"),
    path("sw.js", service_worker, name="service_worker"),
    path("offline/", offline, name="offline"),
]

# ---------------------------------------------------------------------------
# 2-BLOK — TIL-PREFIKSLI ommaviy sahifalar [V2G-T1]
#
# `prefix_default_language=False` → uz (LANGUAGE_CODE) PREFIKSSIZ qoladi:
# mavjud barcha URL'lar, tashqi havolalar va indekslangan sahifalar aynan
# o'zgarishsiz ishlaydi; ingliz UI faqat `/en/...` ostida paydo bo'ladi.
#
# Django 6 LocaleMiddleware prefikssiz yo'lda tilni MAJBURAN LANGUAGE_CODE'ga
# qo'yadi (Accept-Language / cookie / sessiyani e'tiborsiz qoldiradi — qarang
# django/middleware/locale.py). Ya'ni `/janr/melodrama/` ingliz brauzerda ham
# doim o'zbekcha — hreflang e'lon qilgan narsa bilan ziddiyat YO'Q.
#
# Ichki tartib ASL urlpatterns tartibini saqlaydi: drama'ning `<slug:slug>/`
# catch-all'i eng oxirida (shartlar/maxfiylik undan OLDIN turishi shart).
# ---------------------------------------------------------------------------
urlpatterns += i18n_patterns(
    path("users/", include("users.urls", namespace="users")),
    path("billing/", include("billing.urls")),  # checkout + Payme webhook [P7-T2]
    # Huquqiy sahifalar [P10-T5 qisman] — drama catch-all'dan OLDIN turishi shart
    path("yangiliklar/", include("blog.urls", namespace="blog")),  # [V2G-T2]
    path("shartlar/", TemplateView.as_view(template_name="pages/terms.html"), name="terms"),
    path(
        "maxfiylik/",
        TemplateView.as_view(template_name="pages/privacy.html"),
        name="privacy",
    ),
    path("", include("drama.urls", namespace="drama")),
    path("funding/", include("funding.urls")),
    prefix_default_language=False,
)

# Media fayllar uchun (Faqat DEBUG rejimida)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # debug-toolbar [P9-T2]: faqat dev'da o'rnatilgan (import-guard)
    try:
        from debug_toolbar.toolbar import debug_toolbar_urls

        urlpatterns += debug_toolbar_urls()
    except ImportError:
        pass
elif getattr(settings, "SERVE_MEDIA_FROM_STORAGE", False):
    # Test/e2e: InMemoryStorage (disk'da yo'q) -> media'ni storage backend orqali
    # ber, aks holda live_server har poster so'roviga 404 warning yozadi [barqarorlik].
    from django.urls import re_path

    from core.media import serve_from_storage

    _media_prefix = settings.MEDIA_URL.lstrip("/")
    urlpatterns += [
        re_path(rf"^{_media_prefix}(?P<path>.*)$", serve_from_storage, name="test_media"),
    ]

# 404 Xatolik uchun handler
handler404 = "drama.views.error_404"
