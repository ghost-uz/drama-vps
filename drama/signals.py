"""Katalog kesh-invalidatsiya signallari [P9-T1].

Katalogda ko'rinadigan modellar saqlanganda/o'chirilganda versiya bump —
barcha catalog:* kalitlar (yillar/davlatlar/janrlar/slayderlar/similar/
fragmentlar) darhol yangilanadi.

DIQQAT: ``queryset.update()`` bu signallarni CHAQIRMAYDI — o'sha yo'llar
qo'lda bump qiladi (webhook, publish_scheduled_movies, optimize_image_task,
admin publish action'lari). Ro'yxat: docs/ops/caching.md.
"""

from functools import partial

from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save

from .cache import bump_catalog_version
from .models import Category, Episode, Genre, Movie, Season, Tag, TopSlider

# Per-sender ulanish (global receiver EMAS): WatchProgress kabi tez-tez
# yoziladigan modellarga umuman aralashmaymiz.
_CATALOG_MODELS = (Movie, Episode, Season, Genre, Category, Tag, TopSlider)


def invalidate_catalog_cache(sender, instance, **kwargs):
    bump_catalog_version()

    # Trending teglar Movie/Tag'ga bog'liq — yangi hisobni fon (Celery)da
    # darhol tayyorlaymiz (24h TTL'ni kutmasdan; spec'dagi eskirish xavfi).
    if isinstance(instance, Movie | Tag):
        from drama.tasks import recompute_trending_tags

        transaction.on_commit(partial(recompute_trending_tags.delay))


def invalidate_on_m2m(sender, instance, action, **kwargs):
    """movie.tags.add/remove post_save CHAQIRMAYDI — m2m_changed kerak.

    similar_movies (tag-mosligi) va trending shu bog'lanishlarga qurilgan.
    """
    if action in ("post_add", "post_remove", "post_clear"):
        invalidate_catalog_cache(sender, instance, **kwargs)


for _model in _CATALOG_MODELS:
    post_save.connect(
        invalidate_catalog_cache, sender=_model, dispatch_uid=f"catalog_save_{_model.__name__}"
    )
    post_delete.connect(
        invalidate_catalog_cache, sender=_model, dispatch_uid=f"catalog_del_{_model.__name__}"
    )

m2m_changed.connect(
    invalidate_on_m2m, sender=Movie.tags.through, dispatch_uid="catalog_m2m_movie_tags"
)
m2m_changed.connect(
    invalidate_on_m2m, sender=Movie.genres.through, dispatch_uid="catalog_m2m_movie_genres"
)


# --- FTS search_vector yangilash [P8-T1] ---


def schedule_search_vector_update(sender, instance, **kwargs):
    """Movie o'zgardi -> FTS vektorini fon (Celery)da qayta qurish.

    Task queryset.update() ishlatadi -> post_save qayta otilmaydi (loop yo'q).
    """
    from drama.tasks import update_search_vector

    transaction.on_commit(partial(update_search_vector.delay, instance.pk))


def schedule_on_actors_change(sender, instance, action, **kwargs):
    """actors M2M o'zgarishi (B-vazn) — faqat forward (instance=Movie) tomonda.

    Reverse (actor.acted_movies.add) holatida instance=Actor bo'ladi — uning
    pk'sini Movie deb yuborish noto'g'ri; admin oqimi forward ishlatadi.
    """
    if isinstance(instance, Movie) and action in ("post_add", "post_remove", "post_clear"):
        schedule_search_vector_update(sender, instance, **kwargs)


post_save.connect(
    schedule_search_vector_update, sender=Movie, dispatch_uid="search_vector_movie_save"
)
m2m_changed.connect(
    schedule_on_actors_change, sender=Movie.actors.through, dispatch_uid="search_vector_actors"
)
