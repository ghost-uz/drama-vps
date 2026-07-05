# drama/context_processors.py
from django.core.cache import cache
from django.db.models import Count

from .cache import catalog_key
from .models import Tag


def trending_tags(request):
    """Trending teglar — keshdan o'qiladi (recompute_trending_tags task yangilaydi) [P3-T4].

    Kalit versiyalangan [P9-T1] — Movie/Tag o'zgarsa signal bump qiladi va
    task yangi versiya kalitini to'ldiradi. Kesh bo'sh bo'lsa (birinchi
    request / bump'dan keyingi poyga) o'zi hisoblab keshga yozadi.
    """
    key = catalog_key("trending_tags")
    tags = cache.get(key)
    if tags is None:
        tags = list(
            Tag.objects.annotate(movie_count=Count("movies"))
            .filter(movie_count__gt=0)
            .order_by("-movie_count")[:10]
        )
        cache.set(key, tags, 60 * 60 * 24)
    return {"trending_tags": tags}
