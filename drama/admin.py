from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from django.contrib import admin
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin

from .models import (
    Category, Genre, TopSlider, Movie, Episode,
    MovieShots, Actor, Rating, RatingStar, Review
)

# --- INLINES ---

class ReviewInline(TabularInline):
    """Film tahrirlash sahifasida izohlarni chiroyli TAB ichida ko'rsatish"""
    model = Review
    extra = 0
    # Admin faqat o'chirishi yoki ko'rishi mumkin, o'zgartira olmaydi (xavfsizlik uchun)
    readonly_fields = ("user", "parent", "text", "created_at")
    can_delete = True
    tab = True 
    fields = ("user", "parent", "text", "created_at")

class MovieShotsInline(TabularInline):
    model = MovieShots
    extra = 1
    tab = True
    fields = ("title", "image", "display_image")
    readonly_fields = ("display_image",)

    @display(description="Kadr")
    def display_image(self, obj):
        if obj.image:
            return mark_safe(f'<img src="{obj.image.url}" class="rounded h-12 w-20 object-cover" />')
        return "-"

class EpisodeInline(TabularInline):
    model = Episode
    extra = 1
    tab = True 
    fields = ("episode_number", "title", "video_embed_code")
    sortable_field_name = "episode_number"

# --- ADMIN CLASSES ---

@admin.register(Category)
class CategoryAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("name", "slug", "movie_count")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @display(description="Filmlar soni")
    def movie_count(self, obj):
        return obj.movies.count()

@admin.register(Genre)
class GenreAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

@admin.register(Actor)
class ActorAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("display_actor", "original_name", "gender", "age", "birth_date")
    list_filter = ("gender", "birth_date")
    search_fields = ("name", "original_name")
    prepopulated_fields = {"slug": ("name",)}

    @display(description="Aktyor", header=True)
    def display_actor(self, obj):
        img = obj.image.url if obj.image else "https://via.placeholder.com/50"
        return obj.name, obj.original_name, mark_safe(f'<img src="{img}" class="w-10 h-10 rounded-full object-cover" />')

@admin.register(Movie)
class MovieAdmin(ModelAdmin, TranslationAdmin):
    list_display = ("display_header", "year", "category", "get_mdl_rank", "display_status", "is_draft",
    )
    list_filter = ("is_draft", "year", "category", "genres")
    search_fields = ("title", "original_title", "description")
    list_editable = ("is_draft",)
    list_full_width = True
    prepopulated_fields = {"slug": ("title",)}
    
    # Barcha Inlinelar chiroyli TAB tizimida turadi
    inlines = [MovieShotsInline, EpisodeInline, ReviewInline]
    save_on_top = True
    actions = ["publish_movies", "unpublish_movies"]

    fieldsets = (
        ("Asosiy Ma'lumotlar", {"fields": (("title", "original_title", "is_vip"), "slug", "tagline", "description")}),
        ("Media & Vizual", {"classes": ["tab"], "fields": (("poster", "display_poster_preview"), ("film_embed_code", "trailer_embed_code"))}),
        ("Metrikalar va SEO", {"classes": ["tab"], "fields": (("mdl_rank", "site_rank"), "keywords")}),
        ("Texnik Tafsilotlar", {"classes": ["tab"], "fields": (("year", "country"), ("duration", "episodes_count", "age_limit"), "category", "is_draft")}),
        ("Jamoa (M2M)", {"classes": ["collapse"], "fields": (("main_actors", "actors"), "genres")}),
    )

    readonly_fields = ("display_poster_preview", "created_at", "updated_at")

    @display(description="Film", header=True)
    def display_header(self, obj):
        return obj.title, obj.original_title

    @display(description="Poster")
    def display_poster_preview(self, obj):
        if obj.poster:
            return mark_safe(f'<img src="{obj.poster.url}" class="rounded-lg shadow-md" width="100" />')
        return "Rasm yo'q"

    @display(description="Status", label={True: "warning", False: "success"})
    def display_status(self, obj):
        return "Qoralama" if obj.is_draft else "Saytda"

    @display(description="MDL", label=True)
    def get_mdl_rank(self, obj):
        return f"★ {obj.mdl_rank}"

    def unpublish_movies(self, request, queryset):
        queryset.update(is_draft=True)
    unpublish_movies.short_description = "Qoralamaga olish"

    def publish_movies(self, request, queryset):
        queryset.update(is_draft=False)
    publish_movies.short_description = "Nashr etish"


@admin.register(Review)
class ReviewAdmin(ModelAdmin):
    """Alohida Izohlar bo'limi boshqaruvi"""
    list_display = ("user_link", "movie_link", "parent_info", "created_at_formatted", "short_text")
    list_filter = ("created_at", "movie")
    search_fields = ("text", "user__username", "movie__title")
    autocomplete_fields = ["movie", "user"] # User va Movie qidiruvi oson bo'lishi uchun
    
    # Izohlarni o'zgartirishni cheklash (Faqat ko'rish va o'chirish)
    readonly_fields = ("user", "movie", "parent", "created_at")

    @display(description="Foydalanuvchi")
    def user_link(self, obj):
        if obj.user:
            return obj.user.username
        return "Mehmon"

    @display(description="Film")
    def movie_link(self, obj):
        # Film admin sahifasiga havola
        url = reverse("admin:drama_movie_change", args=[obj.movie.id])
        return mark_safe(f'<a href="{url}" class="font-bold text-blue-500 underline">{obj.movie.title}</a>')

    @display(description="Tur", label={"Javob": "info", "Asosiy": "success"})
    def parent_info(self, obj):
        return "Javob" if obj.parent else "Asosiy"

    @display(description="Vaqt")
    def created_at_formatted(self, obj):
        return obj.created_at.strftime("%d.%m.%Y %H:%M")
    
    @display(description="Matn")
    def short_text(self, obj):
        return obj.text[:60] + "..." if len(obj.text) > 60 else obj.text


@admin.register(Rating)
class RatingAdmin(ModelAdmin):
    list_display = ("movie", "star", "ip")
    readonly_fields = ("ip", "movie", "star")

@admin.register(RatingStar)
class RatingStarAdmin(ModelAdmin):
    list_display = ("value",)
    ordering = ("-value",)

@admin.register(TopSlider)
class TopSliderAdmin(ModelAdmin):
    list_display = ("name", "rank", "display_slide")
    
    @display(description="Slayd Rasmi")
    def display_slide(self, obj):
        if obj.image:
            return mark_safe(f'<img src="{obj.image.url}" class="h-12 w-24 object-cover rounded-md" />')
        return "-"

# Admin Panel Sozlamalari
admin.site.site_title = "Drama Portal"
admin.site.site_header = "Drama Uz Boshqaruv Paneli"
admin.site.index_title = "Kino va Seriallar boshqaruvi"