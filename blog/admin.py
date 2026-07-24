"""Blog admin [V2G-T2] — unfold ModelAdmin + TranslationAdmin, Trix rich-text.

Publish/unpublish action'lari `.update()` ishlatadi (signal chaqirmaydi) —
shu bois kesh bump QO'LDA qilinadi (drama/admin.py naqshi).
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.decorators import action

from .cache import bump_blog_version
from .models import Post


class PostAdminForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = "__all__"
        widgets = {
            # Trix rich-text (unfold) — barcha til variantlariga qo'llanadi
            "body": WysiwygWidget,
        }


@admin.register(Post)
class PostAdmin(ModelAdmin, TranslationAdmin):
    form = PostAdminForm
    list_display = ("title", "status", "publish_at", "author", "created_at")
    list_filter = ("status", "tags", "publish_at")
    search_fields = ("title", "slug", "excerpt")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("tags", "related_movies")
    date_hierarchy = "publish_at"
    actions = ["make_published", "make_draft"]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "slug", "excerpt", "body", "cover")}),
        (_("Chop etish"), {"fields": ("status", "publish_at", "author")}),
        (_("Bog'lanishlar"), {"fields": ("tags", "related_movies")}),
        (_("Tizim"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request: HttpRequest, obj: Post, form: Any, change: bool) -> None:
        # Muallif bo'sh bo'lsa — joriy admin
        if obj.author_id is None:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @action(description=_("Chop etish (published)"))
    def make_published(self, request: HttpRequest, queryset: QuerySet[Post]) -> None:
        # publish_at bo'sh bo'lganlarga hozirni qo'yamiz (lenta tartibi)
        queryset.filter(publish_at__isnull=True).update(publish_at=timezone.now())
        updated = queryset.update(status=Post.Status.PUBLISHED)
        bump_blog_version()  # .update() signal chaqirmaydi [P9-T1 naqshi]
        self.message_user(request, _("%(n)d maqola chop etildi.") % {"n": updated})

    @action(description=_("Qoralamaga olish (draft)"))
    def make_draft(self, request: HttpRequest, queryset: QuerySet[Post]) -> None:
        updated = queryset.update(status=Post.Status.DRAFT)
        bump_blog_version()
        self.message_user(request, _("%(n)d maqola qoralamaga olindi.") % {"n": updated})
