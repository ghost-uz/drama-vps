# drama/context_processors.py
from django.db.models import Count

from .models import Tag


def trending_tags(request):
    # Eng ko'p kinoga ega bo'lgan top 10 ta tegni olamiz
    tags = (
        Tag.objects.annotate(movie_count=Count("movies"))
        .filter(movie_count__gt=0)
        .order_by("-movie_count")[:10]
    )

    return {"trending_tags": tags}
