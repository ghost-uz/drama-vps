from modeltranslation.translator import TranslationOptions, register

from .models import Actor, Category, Genre, Movie, MovieShots


@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ("name", "description")


@register(Genre)
class GenreTranslationOptions(TranslationOptions):
    fields = ("name", "description")


@register(Movie)
class MovieTranslationOptions(TranslationOptions):
    # 'keywords' bu ro'yxatda bo'lishi shart!
    fields = ("title", "description", "tagline", "tags")


@register(Actor)
class ActorTranslationOptions(TranslationOptions):
    fields = ("name", "description", "birth_place")


@register(MovieShots)
class MovieShotsTranslationOptions(TranslationOptions):
    fields = ("title", "description")
