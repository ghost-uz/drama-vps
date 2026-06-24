from django.contrib.sitemaps import Sitemap

from .models import Actor, Category, Genre, Movie


class MovieSitemap(Sitemap):
    changefreq = "weekly"  # Kinolar haftada bir yangilanishi mumkin
    priority = 0.9  # Qidiruvda ustunlik darajasi (0.0 dan 1.0 gacha)

    def items(self):
        # Faqat qoralama bo'lmagan kinolarni chiqaramiz
        return Movie.objects.published().order_by("-created_at")

    def lastmod(self, obj):
        # Oxirgi o'zgartirilgan vaqtini ko'rsatish
        return obj.updated_at


class ActorSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return Actor.objects.all()


class CategorySitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.2

    def items(self):
        return Category.objects.all()


class GenreSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return Genre.objects.all()
