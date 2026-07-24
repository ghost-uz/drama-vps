"""Blog RSS feed [V2G-T2] — django.contrib.syndication.

Til-aware: `/yangiliklar/rss/` (uz) va `/en/yangiliklar/rss/` (en) — feed
i18n_patterns ichida, shu bois faol tilda render bo'ladi (title/description
tarjima maydonlaridan). item_link mutlaq URL (Feed framework build_absolute_uri
qiladi).
"""

from __future__ import annotations

from typing import Any

from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.translation import gettext as _

from .models import Post


class LatestPostsFeed(Feed):
    feed_type = Rss201rev2Feed

    def title(self) -> str:
        return _("Drama.Uz — Yangiliklar")

    def description(self) -> str:
        return _("K-drama yangiliklari, sharhlar va tavsiyalar")

    def link(self) -> str:
        return reverse("blog:post_list")

    def items(self) -> Any:
        return Post.objects.published().with_related()[:20]

    def item_title(self, item: Post) -> str:
        return item.title

    def item_description(self, item: Post) -> str:
        return item.summary

    def item_link(self, item: Post) -> str:
        return item.get_absolute_url()

    def item_pubdate(self, item: Post) -> Any:
        return item.publish_at

    def item_updateddate(self, item: Post) -> Any:
        return item.updated_at

    def item_author_name(self, item: Post) -> str | None:
        return item.author.username if item.author else None
