from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from .models import (
    Actor,
    ActorGift,
    Category,
    Episode,
    Genre,
    Movie,
    MovieShots,
    Rating,
    RatingStar,
    Review,
    Season,
    Tag,
    TopSlider,
)

# --- INLINES ---


class ReviewInline(TabularInline):
    model = Review
    extra = 0
    readonly_fields = ("user", "parent", "text", "created_at")
    can_delete = True
    tab = True


class MovieShotsInline(TabularInline):
    model = MovieShots
    extra = 1
    tab = True
    fields = ("title", "image", "display_image")
    readonly_fields = ("display_image",)

    @display(description=_("Kadr"))
    def display_image(self, obj):
        if obj.image:
            return mark_safe(
                f'<img src="{obj.image.url}" class="rounded h-12 w-20 object-cover" />'
            )
        return "-"


class EpisodeInline(TabularInline):
    model = Episode
    extra = 1
    tab = True
    fields = (
        "season",
        "episode_number",
        "title",
        "video_file",
        "upload_status",
        "bunny_video_id",
        "video_embed_code",
    )
    readonly_fields = ("upload_status", "bunny_video_id")
    sortable_field_name = "episode_number"


class SeasonInline(TabularInline):
    model = Season
    extra = 1
    tab = True
    fields = ("number", "title", "year")


# --- ADMIN CLASSES ---


@admin.register(Category)
class CategoryAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("name", "slug", "movie_count")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @display(description=_("Filmlar soni"))
    def movie_count(self, obj):
        return obj.movies.count()


@admin.register(Genre)
class GenreAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)  # Muhim: Autocomplete ishlashi uchun
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Actor)
class ActorAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("display_actor", "gender", "age", "birth_date")
    list_filter = ("gender",)
    search_fields = ("name", "original_name")
    prepopulated_fields = {"slug": ("name",)}

    @display(description=_("Aktyor"), header=True)
    def display_actor(self, obj):
        img = obj.image.url if obj.image else "https://via.placeholder.com/50"
        return (
            obj.name,
            obj.original_name,
            mark_safe(f'<img src="{img}" class="w-10 h-10 rounded-full object-cover" />'),
        )


@admin.register(Movie)
class MovieAdmin(ModelAdmin, TranslationAdmin):
    list_display = (
        "display_header",
        "year",
        "category",
        "get_mdl_rank",
        "get_internal_stats",
        "display_status",
    )
    list_filter = ("status", "is_vip", "year", "category", "genres", "tags")
    search_fields = ("title", "original_title")
    list_full_width = True
    prepopulated_fields = {"slug": ("title",)}

    # Autocomplete: Minglab ma'lumotlar ichidan tez qidirib topish uchun
    autocomplete_fields = ["category", "genres", "tags", "main_actors", "actors"]

    inlines = [SeasonInline, MovieShotsInline, EpisodeInline, ReviewInline]
    save_on_top = True
    actions = ["publish_movies", "unpublish_movies"]

    fieldsets = (
        (
            _("Asosiy Ma'lumotlar"),
            {
                "fields": (
                    ("title", "original_title"),
                    ("slug", "is_vip"),
                    ("status", "publish_at"),
                    "tagline",
                    "description",
                )
            },
        ),
        (
            _("Teglar va SEO"),
            {
                "classes": ["tab"],
                "fields": ("tags",),  # Keywords o'rniga Tags qo'shildi
            },
        ),
        (
            _("Media & Vizual"),
            {
                "classes": ["tab"],
                "fields": (
                    ("poster", "display_poster_preview"),
                    ("bunny_video_id", "bunny_trailer_id"),
                    ("film_embed_code", "trailer_embed_code"),
                ),
            },
        ),
        (
            _("Metrikalar"),
            {
                "classes": ["tab"],
                "fields": (("mdl_rank", "site_rank"), ("average_rating", "total_votes")),
            },
        ),
        (
            _("Texnik Tafsilotlar"),
            {
                "classes": ["tab"],
                "fields": (
                    ("year", "country"),
                    ("duration", "episodes_count", "age_limit"),
                    "category",
                ),
            },
        ),
        (_("Jamoa"), {"classes": ["collapse"], "fields": ("genres", "main_actors", "actors")}),
    )

    readonly_fields = (
        "display_poster_preview",
        "average_rating",
        "total_votes",
        "created_at",
        "updated_at",
    )

    @display(description=_("Film"), header=True)
    def display_header(self, obj):
        return obj.title, obj.original_title

    @display(description=_("Statistika"))
    def get_internal_stats(self, obj):
        return f"⭐ {obj.average_rating} ({obj.total_votes} ovoz)"

    @display(description=_("Poster"))
    def display_poster_preview(self, obj):
        if obj.poster:
            return mark_safe(
                f'<img src="{obj.poster.url}" class="rounded-lg shadow-md" width="100" />'
            )
        return "Rasm yo'q"

    @display(
        description=_("Holat"),
        label={
            "Qoralama": "warning",
            "Rejalashtirilgan": "info",
            "Chop etilgan": "success",
        },
    )
    def display_status(self, obj):
        return obj.get_status_display()

    @display(description="MDL", label=True)
    def get_mdl_rank(self, obj):
        return f"★ {obj.mdl_rank}"

    @admin.action(description=_("Qoralamaga olish"))
    def unpublish_movies(self, request, queryset):
        queryset.update(status=Movie.Status.DRAFT)

    @admin.action(description=_("Nashr etish"))
    def publish_movies(self, request, queryset):
        queryset.update(status=Movie.Status.PUBLISHED)


@admin.register(Season)
class SeasonAdmin(ModelAdmin):
    list_display = ("movie", "number", "title", "year", "episode_count")
    list_filter = ("year",)
    search_fields = ("movie__title", "title")
    autocomplete_fields = ["movie"]

    @display(description=_("Qismlar"))
    def episode_count(self, obj):
        return obj.episodes.count()


@admin.register(Review)
class ReviewAdmin(ModelAdmin):
    list_display = ("user_link", "movie_link", "parent_info", "created_at_formatted", "short_text")
    list_filter = ("created_at", "movie")
    search_fields = ("text", "user__username", "movie__title")
    autocomplete_fields = ["movie", "user"]
    readonly_fields = ("user", "movie", "parent", "created_at")

    @display(description=_("Foydalanuvchi"))
    def user_link(self, obj):
        return obj.user.username if obj.user else "Mehmon"

    @display(description=_("Film"))
    def movie_link(self, obj):
        url = reverse("admin:drama_movie_change", args=[obj.movie.id])
        return mark_safe(
            f'<a href="{url}" class="font-bold text-blue-500 underline">{obj.movie.title}</a>'
        )

    @display(description=_("Tur"), label={"Javob": "info", "Asosiy": "success"})
    def parent_info(self, obj):
        return "Javob" if obj.parent else "Asosiy"

    @display(description=_("Vaqt"))
    def created_at_formatted(self, obj):
        return obj.created_at.strftime("%d.%m.%Y %H:%M")

    @display(description=_("Matn"))
    def short_text(self, obj):
        return obj.text[:60] + "..." if len(obj.text) > 60 else obj.text


@admin.register(TopSlider)
class TopSliderAdmin(ModelAdmin):
    list_display = ("name", "rank", "display_slide")

    @display(description=_("Slayd Rasmi"))
    def display_slide(self, obj):
        if obj.image:
            return mark_safe(
                f'<img src="{obj.image.url}" class="h-12 w-24 object-cover rounded-md" />'
            )
        return "-"


# drama/admin.py fayli


@admin.register(ActorGift)
class ActorGiftAdmin(ModelAdmin):
    # Admin panelda nimalar ko'rinib turishi kerak?
    list_display = ["user", "actor", "get_gift_icon", "price_display", "created_at"]
    list_filter = ["gift_type", "created_at"]
    search_fields = ["user__username", "actor__name"]

    # Jurnal o'zgartirilmasligi uchun o'qish rejimiga o'tkazish
    readonly_fields = ["user", "actor", "gift_type", "price", "created_at"]

    # Chiroyli qilib ko'rsatish funksiyalari
    @admin.display(description="Sovg'a")
    def get_gift_icon(self, obj):
        return obj.get_gift_type_display()

    @admin.display(description="To'langan Coin")
    def price_display(self, obj):
        return mark_safe(
            f'<span style="color: #d4af37; font-weight: bold;">{obj.price} Coin</span>'
        )

    # Admin panelda sovg'a tarixini o'chirish/tahrirlashni taqiqlash (Xavfsizlik)
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(Rating)
admin.site.register(RatingStar)
