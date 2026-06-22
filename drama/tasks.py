"""drama app fon vazifalari — Celery autodiscover shu fayldan topadi."""

import os

from celery import shared_task


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
