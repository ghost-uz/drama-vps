"""drama app fon vazifalari — Celery autodiscover shu fayldan topadi."""

import logging
import os

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def add(x: int, y: int) -> int:
    """Skelet test task — autodiscover va result-backend'ni tasdiqlaydi."""
    return x + y


@shared_task
def ping() -> str:
    return "pong"


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def optimize_image_task(self, app_label, model_name, pk, field_name, max_size, quality):
    """Model rasm maydonini WEBP'ga siqadi (fon, request'ni bloklamasdan).

    `ImageOptimizationMixin.save()` `transaction.on_commit` orqali chaqiradi.
    Loop'siz: siqilgan faylni `.update()` bilan yozadi (model.save()/signal qo'zg'atmaydi).
    Idempotent: maydon allaqachon `.webp` bo'lsa skip qiladi.
    """
    from django.apps import apps

    from core.images import optimize_to_webp

    model = apps.get_model(app_label, model_name)
    try:
        instance = model.objects.get(pk=pk)
    except model.DoesNotExist:
        return  # obyekt o'chirilgan — ish yo'q

    field = getattr(instance, field_name)
    if not field or not field.name:
        return
    if field.name.lower().endswith(".webp"):
        return  # allaqachon optimized (idempotent)

    content = optimize_to_webp(field, tuple(max_size), quality)
    if content is None:
        return  # buzuq/qo'llab-quvvatlanmaydigan format — originalni qoldiramiz (retry'siz)

    try:
        old_name = field.name
        base = os.path.splitext(os.path.basename(old_name))[0]
        field.save(f"{base}.webp", content, save=False)  # storage'ga yozadi (upload_to)
        new_name = field.name
        if new_name != old_name:
            # .update() model.save()/signal CHAQIRMAYDI — cheksiz qayta-siqish loop'ini oldini oladi
            model.objects.filter(pk=pk).update(**{field_name: new_name})
            try:
                field.storage.delete(old_name)  # eski (siqilmagan) faylni tozalaymiz
            except Exception:
                pass
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@shared_task
def recompute_movie_rating(movie_id: int) -> None:
    """Movie.average_rating/total_votes ni UserMovieList.score lardan qayta hisoblaydi.

    Yagona reyting manbai — foydalanuvchi bahosi (UserMovieList.score, 1.0-10.0).
    `.update()` ishlatadi → Movie.save() chaqirmaydi (rasm-task/signal loop'i yo'q).
    Hech kim baholamagan bo'lsa 0/0 ga tushiradi.
    """
    from django.db.models import Avg, Count

    from drama.models import Movie
    from users.models import UserMovieList

    agg = UserMovieList.objects.filter(movie_id=movie_id, score__isnull=False).aggregate(
        avg=Avg("score"), votes=Count("id")
    )
    average = round(agg["avg"], 2) if agg["avg"] is not None else 0
    Movie.objects.filter(pk=movie_id).update(average_rating=average, total_votes=agg["votes"])


@shared_task
def publish_scheduled_movies() -> int:
    """Vaqti yetgan rejalashtirilgan kinolarni 'published' ga o'tkazadi.

    Celery beat har daqiqa chaqiradi (config/celery.py beat_schedule).
    `Movie.objects.due_for_publish()` queryseti tayyor: status=scheduled VA
    publish_at <= hozir bo'lgan kinolarni qaytaradi.
    """
    from drama.models import Movie

    # BULK .update() — Movie.save() chaqirmaydi (rasm/reyting Celery task loop'i yo'q;
    # optimize_image_task / recompute_movie_rating'dagi bir xil mulohaza).
    count = Movie.objects.due_for_publish().update(status=Movie.Status.PUBLISHED)
    if count:
        logger.info("publish_scheduled_movies: %d kino chop etildi", count)
    return count
