# config/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from core.health import healthz, readyz
from drama.sitemaps import ActorSitemap, CategorySitemap, GenreSitemap, MovieSitemap
from drama.views import robots_txt

# Sitemap turlarini ro'yxatga olamiz
sitemaps = {
    "movies": MovieSitemap,
    "actors": ActorSitemap,
    "categories": CategorySitemap,
    "genres": GenreSitemap,
}

urlpatterns = [
    # 1. Admin va tizim yo'llari
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    # Health / readiness (monitoring + Docker healthcheck)
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    # 2. Maxsus SEO fayllar
    path("robots.txt", robots_txt, name="robots_txt"),
    path(
        "sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"
    ),
    # 3. App yo'llari (Namespace bilan)
    path("users/", include("users.urls", namespace="users")),
    # 4. REST API (P2)
    path("api/v1/", include("config.api_urls")),
    path("", include("drama.urls", namespace="drama")),
    path("funding/", include("funding.urls")),
]

# Media fayllar uchun (Faqat DEBUG rejimida)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 404 Xatolik uchun handler
handler404 = "drama.views.error_404"
