"""factory_boy fabrikalari — drama app [P11-T1].

Ishlatish:
    movie = MovieFactory()                              # published, poster bilan
    ep11 = EpisodeFactory(movie=movie, episode_number=11)
    ep12 = EpisodeFactory(movie=movie, episode_number=12)  # o'sha Season 1 ga tushadi
"""

import factory
from django.core.files.uploadedfile import SimpleUploadedFile

from drama.models import Episode, Genre, Movie, Season, Tag


def _poster():
    # Haqiqiy rasm emas: testlarda on_commit bajarilmaydi -> optimizatsiya
    # task'i (P1-T1) ishga tushmaydi, PIL bu baytlarni hech qachon ochmaydi.
    return SimpleUploadedFile("poster.jpg", b"fake-image-bytes", content_type="image/jpeg")


class MovieFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Movie

    title = factory.Sequence(lambda n: f"Movie {n}")
    description = "Test tavsif"
    country = "KR"
    poster = factory.LazyFunction(_poster)


class SeasonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Season
        django_get_or_create = ("movie", "number")  # unique(movie, number) bilan mos

    movie = factory.SubFactory(MovieFactory)
    number = 1


class EpisodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Episode

    movie = factory.SubFactory(MovieFactory)
    # season DOIM episode.movie'ga tegishli ('..movie' — ota deklaratsiyaga havola)
    season = factory.SubFactory(SeasonFactory, movie=factory.SelfAttribute("..movie"))
    title = factory.Sequence(lambda n: f"Episode {n}")
    episode_number = factory.Sequence(lambda n: n + 1)


class GenreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Genre
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Genre {n}")
    slug = factory.Sequence(lambda n: f"genre-{n}")


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tag
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Tag {n}")
    slug = factory.Sequence(lambda n: f"tag-{n}")
