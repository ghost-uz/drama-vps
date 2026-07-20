"""drama/api/serializers.py — katalog API serializerlari [P2-T2].

XAVFSIZLIK: video manbalari (bunny_video_id, *_embed_code) ATAYIN chiqarilmaydi.
Video faqat P2-T4 playback endpoint'ida, gating'dan keyin signed URL bo'lib beriladi.
`fields` aniq ALLOWLIST sifatida yoziladi (exclude EMAS) — yangi maydon tasodifan sizmasin.
"""

from rest_framework import serializers

from drama.models import Actor, Category, Episode, Genre, Movie, Review, Season, Tag


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ("id", "name", "slug")


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name", "slug")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug")


class ActorSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Actor
        fields = ("id", "name", "original_name", "image", "slug", "gender", "age")


class EpisodeSerializer(serializers.ModelSerializer):
    """XAVFSIZ: bunny_video_id / video_embed_code ATAYIN yo'q (P2-T4 gating)."""

    class Meta:
        model = Episode
        fields = ("id", "episode_number", "title", "thumbnail")


class SeasonSerializer(serializers.ModelSerializer):
    episodes = EpisodeSerializer(many=True, read_only=True)

    class Meta:
        model = Season
        fields = ("id", "number", "title", "year", "episodes")


class MovieListSerializer(serializers.ModelSerializer):
    """Yengil ro'yxat ko'rinishi (katalog/qidiruv uchun)."""

    category = CategorySerializer(read_only=True)

    class Meta:
        model = Movie
        fields = (
            "id",
            "title",
            "slug",
            "poster",
            "year",
            "country",
            "average_rating",
            "total_votes",
            "is_vip",
            "category",
        )


class MovieDetailSerializer(serializers.ModelSerializer):
    """To'liq detail. XAVFSIZ: bunny_* va *_embed_code ATAYIN yo'q (P2-T4)."""

    category = CategorySerializer(read_only=True)
    genres = GenreSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    main_actors = ActorSerializer(many=True, read_only=True)
    actors = ActorSerializer(many=True, read_only=True)
    seasons = SeasonSerializer(many=True, read_only=True)

    class Meta:
        model = Movie
        fields = (
            "id",
            "title",
            "original_title",
            "slug",
            "tagline",
            "description",
            "poster",
            "year",
            "country",
            "duration",
            "episodes_count",
            "age_limit",
            "is_vip",
            "mdl_rank",
            "average_rating",
            "total_votes",
            "category",
            "genres",
            "tags",
            "main_actors",
            "actors",
            "seasons",
            "created_at",
        )


class ReviewSerializer(serializers.ModelSerializer):
    """Izoh. user serverda o'rnatiladi (read-only) — klient boshqa user nomidan yoza olmaydi."""

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Review
        fields = (
            "id",
            "movie",
            "user",
            "username",
            "text",
            "parent",
            "is_spoiler",
            "created_at",
        )
        read_only_fields = ("id", "user", "username", "created_at")


class PlaybackSerializer(serializers.Serializer):
    """Playback javobi (signed HLS URL) — OpenAPI hujjat uchun [P2-T4]."""

    episode_id = serializers.IntegerField()
    hls_url = serializers.URLField()
    expires_in = serializers.IntegerField()
