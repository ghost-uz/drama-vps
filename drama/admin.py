from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from core import audit

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
    ReviewReport,
    Season,
    Tag,
    TopSlider,
    UploadStatus,
)

# --- BUNNY VIDEO PIPELINE (P14-T1) ---


class BunnyVideoAdminMixin:
    """Bunny yuklash holati badge'i + retry/refresh action'lari (Episode/Movie umumiy).

    Video fayl admin'dan yuklanadi, qolgani avtomatik (P3-T1 pipeline):
    yaratish -> yuklash -> encoding poll/webhook -> READY'da GUID bog'langan bo'ladi.
    """

    @display(
        description=_("Bunny holati"),
        label={
            UploadStatus.UPLOADING.label: "info",
            UploadStatus.PROCESSING.label: "warning",
            UploadStatus.READY.label: "success",
            UploadStatus.FAILED.label: "danger",
        },
    )
    def display_upload_status(self, obj):
        return obj.get_upload_status_display()

    @admin.action(description=_("Bunny'ga qayta yuklash (lokal fayli borlar)"))
    def retry_bunny_upload(self, request, queryset):
        """Xato/tiqilib qolgan yuklashni NOLdan qayta boshlaydi.

        GUID tozalanadi (Bunny'dagi chala video panelda qoladi — docs/ops/bunny.md),
        pipeline yaratish+yuklashdan qayta yuradi. Lokal fayl o'chirilgan (READY)
        obyektga fayl qayta biriktirilishi kerak.
        """
        from drama.tasks import process_video_upload

        model = queryset.model
        model_name = model._meta.model_name
        queued = skipped = 0
        for obj in queryset:
            if obj.video_file:
                model.objects.filter(pk=obj.pk).update(
                    bunny_video_id="", upload_status=UploadStatus.UPLOADING
                )
                process_video_upload.delay("drama", model_name, obj.pk)
                queued += 1
            else:
                skipped += 1
        if queued:
            messages.success(
                request, f"{queued} ta obyekt Bunny'ga qayta yuklashga navbatga qo'yildi."
            )
        if skipped:
            messages.warning(
                request,
                f"{skipped} ta obyektda lokal video fayl yo'q — "
                "qayta yuklash uchun faylni qayta biriktiring.",
            )

    @admin.action(description=_("Encoding holatini Bunny'dan yangilash"))
    def refresh_bunny_status(self, request, queryset):
        """Tiqilib qolgan PROCESSING uchun poll'ni qayta uyg'otadi.

        Poll retry'lari tugab (10 daqiqa) webhook ham kelmagan bo'lsa, status
        abadiy PROCESSING'da qoladi — bu action yagona davo.
        """
        from drama.tasks import process_video_upload

        model_name = queryset.model._meta.model_name
        queued = 0
        for obj in queryset:
            if obj.bunny_video_id and obj.video_file:
                process_video_upload.delay("drama", model_name, obj.pk)
                queued += 1
        if queued:
            messages.success(request, f"{queued} ta obyekt holati Bunny'dan qayta so'raladi.")
        else:
            messages.warning(
                request, "Mos obyekt yo'q (GUID va lokal fayl mavjudlargina yangilanadi)."
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


class EpisodeInline(BunnyVideoAdminMixin, TabularInline):
    model = Episode
    extra = 1
    tab = True
    fields = (
        "season",
        "episode_number",
        "title",
        "video_file",
        "display_upload_status",
        "bunny_video_id",
        "video_embed_code",
    )
    readonly_fields = ("display_upload_status", "bunny_video_id")
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
class MovieAdmin(BunnyVideoAdminMixin, ModelAdmin, TranslationAdmin):
    list_display = (
        "display_header",
        "year",
        "category",
        "get_mdl_rank",
        "get_internal_stats",
        "display_status",
    )
    list_filter = ("status", "is_vip", "year", "category", "genres", "tags")
    search_fields = ("title", "original_title", "tmdb_id")
    list_full_width = True
    prepopulated_fields = {"slug": ("title",)}

    # Autocomplete: Minglab ma'lumotlar ichidan tez qidirib topish uchun
    autocomplete_fields = ["category", "genres", "tags", "main_actors", "actors"]

    inlines = [SeasonInline, MovieShotsInline, EpisodeInline, ReviewInline]
    save_on_top = True
    actions = ["publish_movies", "unpublish_movies", "retry_bunny_upload", "refresh_bunny_status"]
    # Changelist tepasidagi tugma [V2D-T1] — unfold url_path bo'yicha URL'ni o'zi ulaydi.
    actions_list = ["tmdb_import_view"]

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
                "description": _(
                    "Yakka film videosi: faylni yuklang — Bunny'ga yuborish va GUID "
                    "bog'lash avtomatik (qismlar uchun Qismlar tabidan yuklanadi)."
                ),
                "fields": (
                    ("poster", "display_poster_preview"),
                    ("video_file", "display_upload_status"),
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
                    ("category", "tmdb_id"),
                ),
            },
        ),
        (_("Jamoa"), {"classes": ["collapse"], "fields": ("genres", "main_actors", "actors")}),
    )

    readonly_fields = (
        "display_poster_preview",
        "display_upload_status",
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
        from drama.cache import bump_catalog_version

        count = queryset.update(status=Movie.Status.DRAFT)
        bump_catalog_version()  # .update() signal chaqirmaydi [P9-T1]
        audit.log(request.user, "movie.unpublish", details=f"{count} ta kino", request=request)

    @admin.action(description=_("Nashr etish"))
    def publish_movies(self, request, queryset):
        from drama.cache import bump_catalog_version

        count = queryset.update(status=Movie.Status.PUBLISHED)
        bump_catalog_version()  # .update() signal chaqirmaydi [P9-T1]
        audit.log(request.user, "movie.publish", details=f"{count} ta kino", request=request)

    @action(description=_("TMDB'dan import"), url_path="tmdb-import", icon="download")
    def tmdb_import_view(self, request):
        """TMDB qidiruv/ID -> draft Movie [V2D-T1].

        Metadata sinxron (xato darhol admin'da ko'rinadi [AC-4]), poster va
        aktyor rasmlari Celery'da (tmdb_download_images) — admin bloklanmaydi.
        """
        from drama.services import tmdb

        if not self.has_add_permission(request):
            raise PermissionDenied

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("TMDB'dan import"),
            "query": "",
            "media_type": "tv",
            "results": [],
        }

        if request.method == "POST":
            try:
                media_type, tmdb_id = tmdb.parse_ref(
                    request.POST.get("tmdb_ref", ""),
                    default_type=request.POST.get("media_type", "tv"),
                )
                movie = tmdb.import_movie(media_type, tmdb_id)
            except tmdb.TmdbError as exc:
                messages.error(request, str(exc))
            else:
                audit.log(
                    request.user,
                    "movie.tmdb_import",
                    details=f"{movie.tmdb_id} -> {movie.title} (pk={movie.pk})",
                    request=request,
                )
                messages.success(
                    request,
                    f"«{movie.title}» qoralama sifatida import qilindi — poster va "
                    "aktyor rasmlari fonda yuklanmoqda.",
                )
                return redirect(reverse("admin:drama_movie_change", args=[movie.pk]))
            return render(request, "admin/drama/movie/tmdb_import.html", context)

        query = request.GET.get("q", "").strip()
        media_type = request.GET.get("media_type", "tv")
        if media_type not in ("tv", "movie"):
            media_type = "tv"
        context["query"], context["media_type"] = query, media_type
        if query:
            try:
                context["results"] = tmdb.search_or_lookup(query, media_type)
            except tmdb.TmdbError as exc:
                messages.error(request, str(exc))
        return render(request, "admin/drama/movie/tmdb_import.html", context)


@admin.register(Episode)
class EpisodeAdmin(BunnyVideoAdminMixin, ModelAdmin):
    """Qismlar ro'yxati: yuklash/encoding holatini bir qarashda ko'rish + retry [P14-T1]."""

    list_display = (
        "display_episode",
        "season",
        "display_upload_status",
        "has_bunny_video",
        "created_at",
    )
    list_filter = ("upload_status",)
    search_fields = ("title", "movie__title")
    autocomplete_fields = ["movie", "season"]
    list_select_related = ("movie", "season")
    actions = ["retry_bunny_upload", "refresh_bunny_status"]
    readonly_fields = ("display_upload_status",)
    fieldsets = (
        (
            _("Asosiy"),
            {"fields": (("movie", "season"), ("episode_number", "title"), "thumbnail")},
        ),
        (
            _("Video (Bunny — avtomatik)"),
            {
                "description": _(
                    "Video faylni shu yerga yuklang — Bunny'ga yuborish, encoding va "
                    "GUID bog'lash avtomatik. GUID'ni qo'lda kiritish odatda shart emas "
                    "(faqat favqulodda/legacy holat)."
                ),
                "fields": ("video_file", "display_upload_status", "bunny_video_id"),
            },
        ),
        (
            _("Legacy (qo'lda embed)"),
            {"classes": ["collapse"], "fields": ("video_embed_code",)},
        ),
    )

    @display(description=_("Qism"), header=True)
    def display_episode(self, obj):
        return f"{obj.episode_number}-qism", obj.movie.title

    @admin.display(description=_("Bunny video"), boolean=True)
    def has_bunny_video(self, obj):
        return bool(obj.bunny_video_id)


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
    list_display = (
        "user_link",
        "movie_link",
        "parent_info",
        "created_at_formatted",
        "short_text",
        "is_hidden",
    )
    list_filter = ("is_hidden", "created_at", "movie")
    search_fields = ("text", "user__username", "movie__title")
    autocomplete_fields = ["movie", "user"]
    readonly_fields = ("user", "movie", "parent", "created_at")
    actions = ["hide_reviews", "unhide_reviews"]

    @admin.action(description=_("Yashirish (moderatsiya)"))
    def hide_reviews(self, request, queryset):
        updated = queryset.update(is_hidden=True)
        audit.log(request.user, "review.hide", details=f"{updated} izoh", request=request)
        self.message_user(request, f"{updated} izoh yashirildi.")

    @admin.action(description=_("Qayta ochish"))
    def unhide_reviews(self, request, queryset):
        updated = queryset.update(is_hidden=False)
        audit.log(request.user, "review.unhide", details=f"{updated} izoh", request=request)
        self.message_user(request, f"{updated} izoh qayta ochildi.")

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


@admin.register(ReviewReport)
class ReviewReportAdmin(ModelAdmin):
    """Moderatsiya navbati [P14-T3]: Holat=Kutilmoqda filtri bilan ishlanadi.

    Qabul qilish -> izoh yashiriladi (shu izohning BARCHA ochiq shikoyatlari
    yopiladi — navbat toza qoladi). Rad etish -> agar izoh avto-yashirilgan
    bo'lib, unda boshqa ochiq/qabul shikoyat qolmasa, qayta ochiladi.
    """

    list_display = ("review_excerpt", "movie_title", "reporter", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("review__text", "reporter__username", "review__movie__title")
    list_select_related = ("review", "review__movie", "reporter")
    readonly_fields = ("review", "reporter", "reason", "created_at")
    actions = ["accept_and_hide", "reject_reports"]

    @display(description=_("Izoh"))
    def review_excerpt(self, obj):
        text = obj.review.text
        return (text[:80] + "…") if len(text) > 80 else text

    @display(description=_("Kino"))
    def movie_title(self, obj):
        return obj.review.movie.title

    @admin.action(description=_("Qabul qilish — izohni yashirish"))
    def accept_and_hide(self, request, queryset):
        review_ids = set(queryset.values_list("review_id", flat=True))
        Review.objects.filter(id__in=review_ids).update(is_hidden=True)
        updated = ReviewReport.objects.filter(
            review_id__in=review_ids, status=ReviewReport.Status.PENDING
        ).update(status=ReviewReport.Status.ACCEPTED)
        audit.log(
            request.user,
            "review.moderate.accept",
            details=f"{len(review_ids)} izoh yashirildi, {updated} shikoyat",
            request=request,
        )
        self.message_user(
            request, f"{len(review_ids)} izoh yashirildi, {updated} shikoyat qabul qilindi."
        )

    @admin.action(description=_("Rad etish — asossiz shikoyat"))
    def reject_reports(self, request, queryset):
        updated = queryset.filter(status=ReviewReport.Status.PENDING).update(
            status=ReviewReport.Status.REJECTED
        )
        # Avto-yashirish asossiz chiqqan holat: ochiq/qabul shikoyat qolmagan
        # yashirin izohlarni qayta ochamiz
        review_ids = set(queryset.values_list("review_id", flat=True))
        reopened = 0
        for review in Review.objects.filter(id__in=review_ids, is_hidden=True):
            if not review.reports.exclude(status=ReviewReport.Status.REJECTED).exists():
                review.is_hidden = False
                review.save(update_fields=["is_hidden"])
                reopened += 1
        audit.log(
            request.user,
            "review.moderate.reject",
            details=f"{updated} shikoyat rad, {reopened} izoh qayta ochildi",
            request=request,
        )
        msg = f"{updated} shikoyat rad etildi."
        if reopened:
            msg += f" {reopened} izoh qayta ochildi."
        self.message_user(request, msg)
