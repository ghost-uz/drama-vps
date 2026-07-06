"""users/api/serializers.py — foydalanuvchi/interaksiya serializerlari [P2-T3].

XAVFSIZLIK: balance/xp/is_premium API orqali YOZILMAYDI (read_only) — ular
wallet service (ledger) va tizim tomonidan boshqariladi. Foydalanuvchi faqat
bio/avatar/birth_date ni yangilaydi.
"""

from rest_framework import serializers

from users.models import Profile, UserMovieList, WatchProgress
from users.services import email_verification


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    level = serializers.IntegerField(read_only=True)
    is_currently_premium = serializers.BooleanField(read_only=True)
    email_verified = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = (
            "username",
            "avatar",
            "bio",
            "birth_date",
            "xp",
            "level",
            "balance",
            "is_premium",
            "is_currently_premium",
            "email_verified",
        )
        # XAVFSIZLIK: pul/daraja maydonlari faqat o'qiladi (wallet/tizim manbai)
        read_only_fields = ("xp", "balance", "is_premium")

    def get_email_verified(self, obj: Profile) -> bool:
        """JORIY email tasdiqlanganmi [P6-T1]."""
        return email_verification.is_verified(obj.user)


class WatchlistSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source="movie.title", read_only=True)
    movie_slug = serializers.SlugField(source="movie.slug", read_only=True)

    class Meta:
        model = UserMovieList
        fields = (
            "id",
            "movie",
            "movie_title",
            "movie_slug",
            "status",
            "current_episode",
            "score",
            "updated_at",
        )
        read_only_fields = ("id", "updated_at")


class WatchProgressSerializer(serializers.ModelSerializer):
    percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = WatchProgress
        fields = (
            "id",
            "episode",
            "position_seconds",
            "duration_seconds",
            "completed",
            "percent",
            "updated_at",
        )
        # completed serverda hisoblanadi (90%+ -> True), klient o'zgartira olmaydi
        read_only_fields = ("id", "completed", "updated_at")
