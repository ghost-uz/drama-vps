"""drama/api/urls.py — katalog API router [P2-T2]."""

from rest_framework.routers import DefaultRouter

from .views import (
    ActorViewSet,
    CategoryViewSet,
    GenreViewSet,
    MovieViewSet,
    ReviewViewSet,
    TagViewSet,
)

router = DefaultRouter()
router.register("movies", MovieViewSet, basename="movie")
router.register("genres", GenreViewSet)
router.register("tags", TagViewSet)
router.register("actors", ActorViewSet)
router.register("categories", CategoryViewSet)
router.register("reviews", ReviewViewSet, basename="review")

urlpatterns = router.urls
