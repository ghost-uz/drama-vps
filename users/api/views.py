"""users/api/views.py — foydalanuvchi/interaksiya endpointlari [P2-T3].

Barcha querysetlar request.user bilan filtrlanadi -> boshqa odamning yozuvini
ko'rib/o'zgartirib bo'lmaydi (IDOR himoyasi).
"""

from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from users.models import UserMovieList, WatchProgress

from .serializers import ProfileSerializer, WatchlistSerializer, WatchProgressSerializer


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/me/ — joriy foydalanuvchi profili."""

    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.profile


class WatchlistViewSet(viewsets.ModelViewSet):
    """UserMovieList (shaxsiy ro'yxat). Faqat o'z yozuvlari."""

    serializer_class = WatchlistSerializer
    permission_classes = [IsAuthenticated]
    queryset = UserMovieList.objects.none()  # schema introspection; get_queryset override qiladi

    def get_queryset(self):
        return UserMovieList.objects.filter(profile=self.request.user.profile).select_related(
            "movie"
        )

    def perform_create(self, serializer):
        serializer.save(profile=self.request.user.profile)


class WatchProgressViewSet(viewsets.ModelViewSet):
    """Ko'rish progressi (upsert). POST episode bo'yicha update_or_create; 90%+ -> completed."""

    serializer_class = WatchProgressSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete"]
    queryset = WatchProgress.objects.none()  # schema introspection; get_queryset override qiladi

    def get_queryset(self):
        return WatchProgress.objects.filter(user=self.request.user).select_related(
            "episode", "episode__movie"
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        episode = serializer.validated_data["episode"]
        position = serializer.validated_data.get("position_seconds", 0)
        duration = serializer.validated_data.get("duration_seconds", 0)
        completed = bool(duration and position / duration >= 0.9)
        obj, created = WatchProgress.objects.update_or_create(
            user=request.user,
            episode=episode,
            defaults={
                "position_seconds": position,
                "duration_seconds": duration,
                "completed": completed,
            },
        )
        out = self.get_serializer(obj)
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(out.data, status=code)
