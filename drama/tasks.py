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

    if not field.name.lower().endswith(".webp"):
        content = optimize_to_webp(field, tuple(max_size), quality)
        if content is None:
            return  # buzuq/qo'llab-quvvatlanmaydigan format — originalni qoldiramiz (retry'siz)

        try:
            old_name = field.name
            base = os.path.splitext(os.path.basename(old_name))[0]
            field.save(f"{base}.webp", content, save=False)  # storage'ga yozadi (upload_to)
            new_name = field.name
            if new_name != old_name:
                # .update() model.save()/signal CHAQIRMAYDI — cheksiz qayta-siqish loop'i yo'q
                model.objects.filter(pk=pk).update(**{field_name: new_name})
                # Rasm nomi almashdi — keshlangan fragment/obyektlarda eski
                # (endi o'chiriladigan) URL qolmasin [P9-T1]
                from drama.cache import bump_catalog_version

                bump_catalog_version()
                try:
                    field.storage.delete(old_name)  # eski (siqilmagan) faylni tozalaymiz
                except Exception:
                    pass
        except Exception as exc:
            raise self.retry(exc=exc) from exc

    # -- KARTA VARIANTI (srcset) [P5-T5] --
    # Konfiguratsiya modelning o'zidan o'qiladi (task signature o'zgarmadi);
    # asosiy webp bo'lsa-yu karta bo'sh bo'lsa ham yaratadi (backfill holati).
    card_cfg = getattr(model, "OPTIMIZE_IMAGE_FIELDS", {}).get(field_name, {}).get("card")
    if not card_cfg:
        return
    card_field = getattr(instance, card_cfg["field"], None)
    if card_field is not None and not card_field.name:
        card_content = optimize_to_webp(
            field,
            tuple(card_cfg.get("max_size", (342, 513))),
            card_cfg.get("quality", 78),
        )
        if card_content is None:
            return
        try:
            base = os.path.splitext(os.path.basename(field.name))[0]
            card_field.save(f"{base}_card.webp", card_content, save=False)
            model.objects.filter(pk=pk).update(**{card_cfg["field"]: card_field.name})
            from drama.cache import bump_catalog_version

            bump_catalog_version()
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
        # .update() signal chaqirmaydi -> katalog keshini qo'lda bump [P9-T1]
        from drama.cache import bump_catalog_version

        bump_catalog_version()
        logger.info("publish_scheduled_movies: %d kino chop etildi", count)
    return count


def _run_video_upload(task, app_label: str, model_name: str, pk: int):
    """video_file'li modelni (Episode YOKI Movie) Bunny'ga yuklash umumiy oqimi [P3-T1/P14-T1].

    Talab: modelda `video_file` / `bunny_video_id` / `upload_status` maydonlari
    (drama.models.UploadStatus bilan).

    1-bosqich (GUID yo'q): Bunny'da video yaratadi + faylni yuklaydi.
    2-bosqich (poll): encoding statusini tekshiradi -> tugaguncha retry(countdown).
    Tugagach bunny_video_id qoladi, upload_status=ready, vaqtinchalik fayl o'chadi.
    """
    from django.apps import apps

    from drama.models import UploadStatus
    from drama.services import bunny_upload

    model = apps.get_model(app_label, model_name)
    try:
        obj = model.objects.get(pk=pk)
    except model.DoesNotExist:
        return
    if not obj.video_file:
        return

    try:
        # 1. GUID hali yo'q -> Bunny'da yaratish + faylni yuklash (bir marta)
        if not obj.bunny_video_id:
            guid = bunny_upload.create_video(str(obj))
            with obj.video_file.open("rb") as fh:
                bunny_upload.upload_video(guid, fh.read())
            model.objects.filter(pk=pk).update(
                bunny_video_id=guid, upload_status=UploadStatus.PROCESSING
            )
            obj.bunny_video_id = guid

        # 2. Encoding statusini tekshirish
        status = bunny_upload.get_status(obj.bunny_video_id)
    except Exception as exc:
        logger.warning("process_video_upload(%s.%s %s) xato: %s", app_label, model_name, pk, exc)
        raise task.retry(exc=exc) from exc

    if status >= bunny_upload.STATUS_ERROR:
        model.objects.filter(pk=pk).update(upload_status=UploadStatus.FAILED)
        return
    if status < bunny_upload.STATUS_FINISHED:
        raise task.retry(countdown=30)  # hali encoding tugamagan

    # Tugadi: vaqtinchalik (lokal) faylni tozalab, ready holatga o'tkazamiz
    obj.video_file.delete(save=False)
    model.objects.filter(pk=pk).update(upload_status=UploadStatus.READY, video_file="")


@shared_task(bind=True, max_retries=20, default_retry_delay=30)
def process_video_upload(self, app_label: str, model_name: str, pk: int):
    """Episode yoki Movie video faylini Bunny'ga yuklaydi (yagona kirish nuqtasi)."""
    _run_video_upload(self, app_label, model_name, pk)


@shared_task(bind=True, max_retries=20, default_retry_delay=30)
def process_episode_upload(self, episode_id: int):
    """Eski nom [P3-T1] — deploy paytida navbatda qolgan xabarlar uchun saqlangan.

    Yangi kod `process_video_upload` ishlatadi.
    """
    _run_video_upload(self, "drama", "episode", episode_id)


@shared_task
def recompute_trending_tags() -> int:
    """Trending teglarni qayta hisoblab keshga yozadi [P3-T4].

    context_processor keshdan o'qiydi -> har request'da og'ir annotate-Count
    so'rovi bajarilmaydi. Kalit versiyalangan [P9-T1]: Movie/Tag saqlanganda
    signal bump + shu task'ni qayta navbatga qo'yadi — 24h TTL zaxira xolos.
    """
    from django.core.cache import cache
    from django.db.models import Count

    from drama.cache import catalog_key
    from drama.models import Tag

    tags = list(
        Tag.objects.annotate(movie_count=Count("movies"))
        .filter(movie_count__gt=0)
        .order_by("-movie_count")[:10]
    )
    cache.set(catalog_key("trending_tags"), tags, 60 * 60 * 24)
    return len(tags)


@shared_task
def update_search_vector(movie_id: int) -> bool:
    """Movie.search_vector'ni qayta quradi [P8-T1] (signal -> on_commit -> shu task).

    Vaznlar: A=title(uz/en)+original, B=aktyor ismlari, C=tavsif(uz/en).
    config='simple' — postgres'da o'zbekcha stemmer yo'q; so'zma-so'z indeks +
    trigram (xato-bardosh) kombinatsiyasi to'g'ri natija beradi.
    queryset.update() ishlatiladi -> post_save QAYTA otilmaydi (loop yo'q).
    sqlite (dev/test fallback)da no-op.
    """
    from django.db import connection

    if connection.vendor != "postgresql":
        return False

    from django.contrib.postgres.search import SearchVector
    from django.db.models import Value

    from drama.models import Movie

    movie = Movie.objects.filter(pk=movie_id).first()
    if movie is None:
        return False

    actors_text = " ".join(movie.actors.order_by("name").values_list("name", flat=True))
    vector = (
        SearchVector("title", "title_uz", "title_en", "original_title", weight="A", config="simple")
        + SearchVector(Value(actors_text), weight="B", config="simple")
        + SearchVector(
            "description", "description_uz", "description_en", weight="C", config="simple"
        )
    )
    Movie.objects.filter(pk=movie_id).update(search_vector=vector)
    return True
