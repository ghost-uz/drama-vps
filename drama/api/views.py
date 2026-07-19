"""drama/api/views.py — katalog ReadOnly ViewSet'lari [P2-T2].

Public katalog: MovieViewSet faqat Movie.objects.published() ni ko'rsatadi
(self-healing scheduled bilan). list/retrieve uchun N+1'siz optimallashtirilgan.
"""

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from drama.bunny_stream import (
    is_configured,
    signed_hls_url,
    token_expiry_seconds,
    token_user_ip,
)
from drama.models import Actor, Category, Episode, Genre, Movie, Review, Season, Tag
from drama.services.playback import get_episode_access
from users.api.permissions import IsOwnerOrAdmin

from .filters import MovieFilter
from .pagination import ReviewCursorPagination
from .serializers import (
    ActorSerializer,
    CategorySerializer,
    GenreSerializer,
    MovieDetailSerializer,
    MovieListSerializer,
    PlaybackSerializer,
    ReviewSerializer,
    TagSerializer,
)


class MovieSearchFilter(SearchFilter):
    """?search= endi FTS+trigram [P8-T1] (postgres; sqlite'da icontains fallback).

    SearchFilter'dan meros — search param nomi va OpenAPI hujjati o'zgarmaydi.
    Servis o'z relevantlik order_by'sini qo'yadi, shu sabab bu backend
    OrderingFilter'dan KEYIN turadi (qidiruvda relevantlik ustun).
    """

    def filter_queryset(self, request, queryset, view):
        term = (request.query_params.get(self.search_param) or "").strip()
        if not term:
            return queryset
        from drama.services import search as search_service

        return search_service.search_movies(queryset, term)


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    lookup_field = "slug"
    # MovieSearchFilter OXIRIDA: qidiruvda relevantlik tartibi ordering'dan ustun
    filter_backends = [DjangoFilterBackend, OrderingFilter, MovieSearchFilter]
    filterset_class = MovieFilter
    search_fields = ["title", "original_title"]  # OpenAPI hujjat uchun saqlangan
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
    # [P9-T3] Izohlar cheksiz o'sadi -> cursor (movies PageNumber'da qoladi)
    pagination_class = ReviewCursorPagination

    def get_queryset(self):
        qs = Review.objects.select_related("user", "movie", "episode").order_by("-created_at")
        movie_slug = self.request.query_params.get("movie")
        if movie_slug:
            qs = qs.filter(movie__slug=movie_slug)
        # [V2B-T3] ?episode=<id>: shu qism izohlari + UMUMIY (episode=null) —
        # HTML tomondagi "Shu qism muhokamasi" bilan bir xil semantika
        episode_id = self.request.query_params.get("episode")
        if episode_id:
            try:
                episode_pk = int(episode_id)
            except ValueError:
                return qs.none()
            qs = qs.filter(Q(episode_id=episode_pk) | Q(episode__isnull=True))
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


class EpisodePlaybackView(APIView):
    """GET /api/v1/episodes/{id}/playback/ — gating + signed Bunny URL [P2-T4].

    Gating yagona service (get_episode_access) orqali — HTML view bilan bir manba.
    Ruxsat bo'lsa qisqa muddatli (4 soat) signed HLS URL; ruxsatsizga 403.
    Bu pleyer (web+mobil) uchun yagona xavfsiz video manbai.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "playback"

    @extend_schema(
        responses={
            200: PlaybackSerializer,
            403: OpenApiResponse(description="Ko'rish ruxsati yo'q (gating)"),
            404: OpenApiResponse(description="Video mavjud emas"),
        }
    )
    def get(self, request, pk):
        episode = get_object_or_404(Episode.objects.select_related("movie"), pk=pk)
        allowed, restriction = get_episode_access(request.user, episode)
        if not allowed:
            return Response(
                {"detail": "Bu qismni ko'rish uchun ruxsat yo'q.", "restriction": restriction},
                status=403,
            )
        if not episode.bunny_video_id or not is_configured():
            return Response({"detail": "Video hozircha mavjud emas."}, status=404)
        return Response(
            {
                "episode_id": episode.id,
                "hls_url": signed_hls_url(episode.bunny_video_id, user_ip=token_user_ip(request)),
                "expires_in": token_expiry_seconds(),
            }
        )
