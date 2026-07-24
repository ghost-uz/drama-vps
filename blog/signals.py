"""Blog kesh invalidatsiyasi [V2G-T2].

Post o'zgarsa (save/delete) blog versiyasini bump qilamiz — lenta, list va
homepage "Yangiliklar" bloki keshdan yangilanadi. Movie'ning katalog-signal
naqshi bilan bir xil (drama/signals.py).

⚠️ Admin publish/unpublish action'lari `.update()` ishlatadi — u signal
CHAQIRMAYDI, shu bois u yerda bump QO'LDA qilinadi (blog/admin.py).
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .cache import bump_blog_version
from .models import Post


@receiver(post_save, sender=Post)
@receiver(post_delete, sender=Post)
def _invalidate_on_post_change(sender: type[Post], **kwargs: Any) -> None:
    bump_blog_version()


@receiver(m2m_changed, sender=Post.tags.through)
@receiver(m2m_changed, sender=Post.related_movies.through)
def _invalidate_on_m2m(sender: Any, action: str, **kwargs: Any) -> None:
    # Faqat haqiqiy o'zgarishlarda (post_* action'lar) — pre_* ni o'tkazamiz
    if action in {"post_add", "post_remove", "post_clear"}:
        bump_blog_version()
