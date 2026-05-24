from modeltranslation.translator import register, TranslationOptions
from .models import Category, Genre, Movie, Actor, MovieShots

@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ('name', 'description')

@register(Genre)
class GenreTranslationOptions(TranslationOptions):
    fields = ('name', 'description')

@register(Movie)
class MovieTranslationOptions(TranslationOptions):
    # 'keywords' bu ro'yxatda bo'lishi shart!
    fields = ('title', 'description', 'tagline', 'tags')

@register(Actor)
class ActorTranslationOptions(TranslationOptions):
    fields = ('name', 'description', 'birth_place')

@register(MovieShots)
class MovieShotsTranslationOptions(TranslationOptions):
    fields = ('title', 'description')