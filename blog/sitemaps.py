"""Blog sitemap [V2G-T2] — faqat published; i18n alternates (V2G-T1 mixin)."""

from __future__ import annotations

from typing import Any

from drama.sitemaps import I18nSitemap

from .models import Post


class PostSitemap(I18nSitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self) -> Any:
        return Post.objects.published().order_by("-publish_at", "-created_at")

    def lastmod(self, obj: Post) -> Any:
        return obj.updated_at
