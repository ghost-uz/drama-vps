"""Mavjud UserMovieList.score lardan Movie.average_rating/total_votes ni seed qiladi.

P1-T5: reyting yagona manbai endi foydalanuvchi bahosi. Denormalizatsiyani bir marta
to'ldiradi (keyin signal + recompute_movie_rating Celery task yangilab boradi).
Reversible: orqaga 0/0 ga qaytaradi.
"""

from django.db import migrations
from django.db.models import Avg, Count


def backfill_movie_ratings(apps, schema_editor):
    Movie = apps.get_model("drama", "Movie")
    UserMovieList = apps.get_model("users", "UserMovieList")

    rows = (
        UserMovieList.objects.filter(score__isnull=False)
        .values("movie_id")
        .annotate(avg=Avg("score"), votes=Count("id"))
    )
    for row in rows:
        Movie.objects.filter(pk=row["movie_id"]).update(
            average_rating=round(row["avg"], 2), total_votes=row["votes"]
        )


def reset_movie_ratings(apps, schema_editor):
    Movie = apps.get_model("drama", "Movie")
    Movie.objects.update(average_rating=0, total_votes=0)


class Migration(migrations.Migration):

    dependencies = [
        ("drama", "0019_alter_average_rating_max_digits"),
        ("users", "0004_profile_xp_usermovielist"),
    ]

    operations = [
        migrations.RunPython(backfill_movie_ratings, reset_movie_ratings),
    ]
