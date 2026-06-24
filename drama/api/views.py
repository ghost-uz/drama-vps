"""drama/api/views.py — katalog ReadOnly ViewSet'lari [P2-T2].

Public katalog: MovieViewSet faqat Movie.objects.published() ni ko'rsatadi
(self-healing scheduled bilan). list/retrieve uchun N+1'siz optimallashtirilgan.
"""

from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from drama.models import Actor, Category, Genre, Movie, Review, Season, Tag
from users.api.permissions import IsOwnerOrAdmin

from .filters import MovieFilter
from .serializers import (
    ActorSerializer,
    CategorySerializer,
    GenreSerializer,
    MovieDetailSerializer,
    MovieListSerializer,
    ReviewSerializer,
    TagSerializer,
)


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    lookup_field = "slug"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MovieFilter
    search_fields = ["title", "original_title"]
    ordering_fields = ["year", "average_rating", "created_at", "mdl_rank"]
    ordering = ["-created_at"]  # default tartib

    def get_throttles(self):
        # Qidiruv (og'ir ILIKE) uchun alohida throttle byudjeti (search scope)
        if self.action == "list" and self.request.query_params.get("search"):
            self.throttle_scope = "search"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        qs = Movie.objects.published().select_related("category")
        if self.action == "retrieve":
            # Detail: nested seasons->episodes + M2M lar bitta marta prefetch (N+1 yo'q)
            return qs.prefetch_related(
                "genres",
                "tags",
                "main_actors",
                "actors",
                Prefetch("seasons", queryset=Season.objects.prefetch_related("episodes")),
            )
        # List: yengil; tartib OrderingFilter (default -created_at) orqali
        return qs

    def get_serializer_class(self):
        return MovieDetailSerializer if self.action == "retrieve" else MovieListSerializer


class GenreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Genre.objects.all().order_by("name")
    serializer_class = GenreSerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter]
    search_fields = ["name"]


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all().order_by("name")
    serializer_class = TagSerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter]
    search_fields = ["name"]


class ActorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Actor.objects.all().order_by("name")
    serializer_class = ActorSerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter]
    search_fields = ["name", "original_name"]


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter]
    search_fields = ["name"]


class ReviewViewSet(viewsets.ModelViewSet):
    """Izohlar: list public, create JWT+throttle(10/soat), destroy egasi/admin.

    `?movie=<slug>` bilan kino bo'yicha filtrlanadi.
    """

    serializer_class = ReviewSerializer
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        qs = Review.objects.select_related("user", "movie").order_by("-created_at")
        movie_slug = self.request.query_params.get("movie")
        if movie_slug:
            qs = qs.filter(movie__slug=movie_slug)
        return qs

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        if self.action == "destroy":
            return [IsOwnerOrAdmin()]
        return [AllowAny()]  # list/retrieve public

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "review"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
