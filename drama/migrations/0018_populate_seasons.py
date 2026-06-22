"""Data migration: mavjud episodelarni har Movie uchun "Season 1"ga bog'lash (P1-T2)."""

from django.db import migrations


def create_default_seasons(apps, schema_editor):
    Movie = apps.get_model("drama", "Movie")
    Season = apps.get_model("drama", "Season")
    Episode = apps.get_model("drama", "Episode")

    # Episodelari bor har bir Movie uchun "Season 1" yaratamiz va bog'laymiz.
    for movie in Movie.objects.filter(episodes__isnull=False).distinct():
        season, _ = Season.objects.get_or_create(
            movie=movie, number=1, defaults={"title": "", "year": movie.year}
        )
        Episode.objects.filter(movie=movie, season__isnull=True).update(season=season)


def remove_default_seasons(apps, schema_editor):
    Episode = apps.get_model("drama", "Episode")
    Season = apps.get_model("drama", "Season")
    Episode.objects.update(season=None)
    Season.objects.filter(number=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("drama", "0017_add_season"),
    ]

    operations = [
        migrations.RunPython(create_default_seasons, remove_default_seasons),
    ]
