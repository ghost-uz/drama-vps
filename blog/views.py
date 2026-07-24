"""Blog views [V2G-T2] — list + detail, keshlangan, faqat published ommaviy."""

from __future__ import annotations

from typing import Any

from django.views.generic import DetailView, ListView

from .cache import blog_key
from .models import Post
from .seo import article_jsonld


class PostListView(ListView):
    """Yangiliklar lentasi — faqat ommaviy, sahifalangan."""

    template_name = "blog/post_list.html"
    context_object_name = "posts"
    paginate_by = 12

    def get_queryset(self) -> Any:
        return Post.objects.published().with_related()


class PostDetailView(DetailView):
    """Maqola sahifasi — ommaviy bo'lmasa 404 (draft/kelajakdagi scheduled yashirin)."""

    template_name = "blog/post_detail.html"
    context_object_name = "post"

    def get_queryset(self) -> Any:
        # published() manager draft/kelajakni CHIQARIB tashlaydi -> to'g'ridan 404
        return Post.objects.published().with_related().prefetch_related("related_movies")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        post: Post = context["post"]
        context["article_jsonld"] = article_jsonld(self.request, post)
        # Bog'liq kinolar (SEO ichki havola) — published bo'lganlari
        context["related_movies"] = post.related_movies.published()[:6]
        return context


def blog_widget_posts(limit: int = 4) -> list[Post]:
    """Homepage 'Yangiliklar' bloki uchun eng so'nggi ommaviy maqolalar (keshlangan).

    Kesh QIYMATI model-instansiyalar emas, chunki ular pickle'langanda katta;
    lekin bu kichik ro'yxat (<=4) va lenta bilan bir xil versiyalangan kalitda —
    Post o'zgarsa signal bump qiladi. Oddiylik uchun querysetni ro'yxatga aylantiramiz.
    """
    from django.core.cache import cache

    key = blog_key(f"widget:{limit}")
    posts = cache.get(key)
    if posts is None:
        posts = list(Post.objects.published().with_related()[:limit])
        cache.set(key, posts, 6 * 60 * 60)
    return posts
