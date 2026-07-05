"""Mavjud (siqilmagan) rasmlarni WEBP'ga siqish — bir martalik backfill (P1-T1).

ImageOptimizationMixin'li barcha modellarni aylanib, `.webp` bo'lmagan rasmlarni
Celery task'ga beradi (yoki `--sync` bilan shu yerda siqadi).

    python manage.py optimize_images            # Celery'ga navbatga qo'yadi
    python manage.py optimize_images --sync     # worker'siz, shu yerda siqadi
    python manage.py optimize_images --dry-run  # faqat sanaydi
"""

from django.apps import apps
from django.core.management.base import BaseCommand

from core.images import ImageOptimizationMixin


class Command(BaseCommand):
    help = "Mavjud rasmlarni WEBP'ga siqadi (ImageOptimizationMixin modellari)."

    def add_arguments(self, parser):
        parser.add_argument("--sync", action="store_true", help="Celery'siz, shu jarayonda siqish")
        parser.add_argument(
            "--dry-run", action="store_true", help="Faqat sanash, hech narsa siqmaslik"
        )

    def handle(self, *args, **options):
        from drama.tasks import optimize_image_task

        sync = options["sync"]
        dry = options["dry_run"]
        total = 0

        for model in apps.get_models():
            if not issubclass(model, ImageOptimizationMixin):
                continue
            fields = getattr(model, "OPTIMIZE_IMAGE_FIELDS", {})
            if not fields:
                continue
            label = model._meta.app_label
            name = model._meta.model_name

            for obj in model.objects.all().iterator():
                for field_name, cfg in fields.items():
                    field = getattr(obj, field_name)
                    if not field or not field.name:
                        continue
                    # Asosiy webp bo'lsa ham karta varianti bo'sh bo'lsa navbatga [P5-T5]
                    card_cfg = cfg.get("card")
                    card_missing = bool(card_cfg) and not getattr(obj, card_cfg["field"], None)
                    if field.name.lower().endswith(".webp") and not card_missing:
                        continue
                    total += 1
                    self.stdout.write(f"  {label}.{name}#{obj.pk}.{field_name}: {field.name}")
                    if dry:
                        continue
                    max_size = list(cfg.get("max_size", (1280, 1280)))
                    quality = cfg.get("quality", 80)
                    payload = [label, name, obj.pk, field_name, max_size, quality]
                    if sync:
                        optimize_image_task.apply(args=payload)
                    else:
                        optimize_image_task.delay(*payload)

        verb = "topildi" if dry else ("siqildi" if sync else "navbatga qo'yildi")
        self.stdout.write(self.style.SUCCESS(f"\n{total} ta rasm {verb}."))
