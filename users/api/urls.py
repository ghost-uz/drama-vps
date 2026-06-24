"""users/api/urls.py — foydalanuvchi API yo'llari [P2-T3]."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import MeView, WatchlistViewSet, WatchProgressViewSet

router = DefaultRouter()
router.register("watchlist", WatchlistViewSet, basename="watchlist")
router.register("watch-progress", WatchProgressViewSet, basename="watch-progress")

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    *router.urls,
]
