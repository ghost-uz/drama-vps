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
    # 'tags' (M2M) OLIB TASHLANDI: modeltranslation M2M'ni qo'llab-quvvatlamaydi —
    # tags_uz/tags_en bir xil related_name='movies' bilan reverse accessor'ni buzgan,
    # trending_tags Count("movies") doim 0 bo'lgan. Teg tilga bog'liq emas.
    fields = ("title", "description", "tagline")


@register(Actor)
class ActorTranslationOptions(TranslationOptions):
    fields = ("name", "description", "birth_place")


@register(MovieShots)
class MovieShotsTranslationOptions(TranslationOptions):
    fields = ("title", "description")
