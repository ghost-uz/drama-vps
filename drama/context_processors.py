# drama/context_processors.py
from django.core.cache import cache
from django.db.models import Count

from .models import Tag


def trending_tags(request):
    """Trending teglar — keshdan o'qiladi (recompute_trending_tags task yangilaydi) [P3-T4].

    Kesh bo'sh bo'lsa (birinchi marta / TTL tugadi) o'zi hisoblaydi va keshga yozadi.
    """
    tags = cache.get("trending_tags")
    if tags is None:
        tags = list(
            Tag.objects.annotate(movie_count=Count("movies"))
            .filter(movie_count__gt=0)
            .order_by("-movie_count")[:10]
        )
        cache.set("trending_tags", tags, 60 * 60 * 24)
    return {"trending_tags": tags}
