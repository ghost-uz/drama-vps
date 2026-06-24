"""config/api_urls.py — /api/v1/ REST API yo'llari [P2-T1].

App-darajadagi router'lar (drama/api, users/api) bu yerga P2-T2+ da ulanadi.
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

app_name = "api"

urlpatterns = [
    # Katalog API (router: movies, genres, tags, actors, categories) [P2-T2]
    path("", include("drama.api.urls")),
    # Foydalanuvchi API (me, watchlist, watch-progress) [P2-T3]
    path("", include("users.api.urls")),
    # OpenAPI sxema + interaktiv hujjatlar
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
    # JWT autentifikatsiya (access/refresh/verify)
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]
