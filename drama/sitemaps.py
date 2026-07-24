from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Actor, Category, Genre, Movie


class I18nSitemap(Sitemap):
    """Har item uchun uz + /en/ variant + hreflang alternates [V2G-T1].

    Django i18n sitemap'i har til uchun alohida <url> yozadi va `alternates`
    orqali har biriga xhtml:link (hreflang) qo'shadi; `x_default` esa default
    (uz, prefikssiz) variantni x-default sifatida e'lon qiladi. `location()`
    til-neytral get_absolute_url'ni qaytaradi — prefiksni Django qo'yadi.
    """

    i18n = True
    alternates = True
    x_default = True


class MovieSitemap(I18nSitemap):
    changefreq = "weekly"  # Kinolar haftada bir yangilanishi mumkin
    priority = 0.9  # Qidiruvda ustunlik darajasi (0.0 dan 1.0 gacha)

    def items(self):
        # Faqat qoralama bo'lmagan kinolarni chiqaramiz
        return Movie.objects.published().order_by("-created_at")

    def lastmod(self, obj):
        # Oxirgi o'zgartirilgan vaqtini ko'rsatish
        return obj.updated_at


class ActorSitemap(I18nSitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        # order_by'siz Paginator beqaror edi (UnorderedObjectListWarning) [P5-T5]
        return Actor.objects.all().order_by("id")


class CategorySitemap(I18nSitemap):
    changefreq = "monthly"
    priority = 0.2

    def items(self):
        return Category.objects.all().order_by("id")


class GenreSitemap(I18nSitemap):
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


class StaticPagesSitemap(I18nSitemap):
    """Statik huquqiy sahifalar (oferta/maxfiylik) [P10-T5 qisman]."""

    changefreq = "yearly"
    priority = 0.3

    def items(self):
        return ["terms", "privacy"]

    def location(self, item):
        return reverse(item)
