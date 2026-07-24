"""Blog JSON-LD [V2G-T2] — schema.org Article + BreadcrumbList.

drama/seo.py `to_jsonld` xavfsiz seriyalashtiruvchisini qayta ishlatadi
(mark_safe + `<` -> \\u003c, XSS-himoya).
"""

from __future__ import annotations

from django.http import HttpRequest
from django.urls import reverse

from drama.seo import to_jsonld

from .models import Post


def article_jsonld(request: HttpRequest, post: Post) -> str:
    """Maqola sahifasi grafi: Article + BreadcrumbList (Bosh > Yangiliklar > Maqola)."""
    url = request.build_absolute_uri(post.get_absolute_url())
    blog_url = request.build_absolute_uri(reverse("blog:post_list"))
    home_url = request.build_absolute_uri("/")

    article: dict = {
        "@type": "Article",
        "headline": post.title,
        "description": post.summary,
        "url": url,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "inLanguage": getattr(request, "LANGUAGE_CODE", "uz"),
    }
    if post.publish_at:
        article["datePublished"] = post.publish_at.isoformat()
    article["dateModified"] = post.updated_at.isoformat()
    if post.cover:
        article["image"] = request.build_absolute_uri(post.cover.url)
    if post.author:
        article["author"] = {"@type": "Person", "name": post.author.username}
    article["publisher"] = {
        "@type": "Organization",
        "name": "Drama.Uz",
        "url": home_url,
    }

    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Bosh sahifa", "item": home_url},
            {"@type": "ListItem", "position": 2, "name": "Yangiliklar", "item": blog_url},
            {"@type": "ListItem", "position": 3, "name": post.title, "item": url},
        ],
    }

    return to_jsonld({"@context": "https://schema.org", "@graph": [article, breadcrumb]})
