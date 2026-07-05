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
        # order_by'siz Paginator beqaror edi (UnorderedObjectListWarning) [P5-T5]
        return Actor.objects.all().order_by("id")


class CategorySitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.2

    def items(self):
        return Category.objects.all().order_by("id")


class GenreSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return Genre.objects.all().order_by("id")


class VideoSitemap(Sitemap):
    """Google video sitemap [P5-T5] — /sitemap-video.xml (video namespace).

    Faqat haqiqiy video kontentli published kinolar (epizodli yoki yakka film
    bunny_video_id bilan). Shablon: templates/sitemaps/sitemap-video.xml.
    """

    changefreq = "weekly"
    priority = 0.8

    def items(self):
        from django.db.models import Q

        return (
            Movie.objects.published()
            .filter(Q(episodes__isnull=False) | ~Q(bunny_video_id=""))
            .distinct()
            .order_by("-created_at")
        )

    def lastmod(self, obj):
        return obj.updated_at
