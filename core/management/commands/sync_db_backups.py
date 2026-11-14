"""DB dumplarini GCS'ga qo'lda sinxronlash + bucket tayyorlash [R0-T4].

    python manage.py sync_db_backups                  # yo'q dumplarni yuklash
    python manage.py sync_db_backups --create-bucket  # avval bucket'ni tayyorlash
                                                      # (idempotent: bor bo'lsa
                                                      # lifecycle/PAP to'ldiriladi)

Kunlik avtomatik yo'l — core.tasks.offsite_db_backup_task (beat 08:30 Tashkent);
bu buyruq birinchi sozlash va qo'lda tekshirish uchun. Prod'da web konteynerda
EMAS, celery-worker'da ishga tushiring: dbbackups volume faqat unda mount
qilingan (docker-compose.prod.yml):

    docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        exec celery-worker python manage.py sync_db_backups
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.offsite_backup import ensure_backup_bucket, sync_db_backups


class Command(BaseCommand):
    help = "DB dumplarini GCS'ga off-site sinxronlaydi (--create-bucket bilan tayyorlaydi)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--create-bucket",
            action="store_true",
            help="Bucket yo'q bo'lsa yaratadi; bor bo'lsa lifecycle/PAP'ni to'ldiradi.",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            default=60,
            help="GCS lifecycle: dump necha kundan keyin avtomatik o'chadi (default 60).",
        )
        parser.add_argument(
            "--location",
            default=None,
            help="Yangi bucket joylashuvi (default: CDN bucket bilan bir xil).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.GCS_BACKUP_BUCKET:
            raise CommandError(
                "GCS_BACKUP_BUCKET bo'sh. .env'ga bucket nomini yozing (masalan "
                "my-drama-uz-db-backups) va konteynerni qayta yarating — "
                "docs/ops/backup.md 'Off-site' bo'limi."
            )

        from google.api_core.exceptions import Conflict, Forbidden

        if options["create_bucket"]:
            try:
                summary = ensure_backup_bucket(
                    retention_days=options["retention_days"], location=options["location"]
                )
            except Forbidden as exc:
                raise CommandError(
                    "Service-account'da bucket yaratish/boshqarish huquqi yo'q "
                    "(storage.buckets.create). Egasi GCP konsolda bucket'ni qo'lda "
                    f"yaratsin (nom: {settings.GCS_BACKUP_BUCKET}, private, uniform ACL, "
                    f"lifecycle {options['retention_days']} kun) va SA'ga shu bucket'da "
                    f"roles/storage.objectAdmin bersin. Asl xato: {exc}"
                ) from exc
            except Conflict as exc:
                raise CommandError(
                    f"Bucket nomi '{settings.GCS_BACKUP_BUCKET}' band (nomlar GLOBAL "
                    "unikal). .env'da boshqa nom tanlang, masalan loyiha-prefiksli "
                    f"'my-drama-uz-db-backups'. Asl xato: {exc}"
                ) from exc
            self.stdout.write(self.style.SUCCESS(f"  + {summary}"))

        try:
            result = sync_db_backups()
        except Forbidden as exc:
            raise CommandError(
                f"GCS ruxsat xatosi — SA'ga gs://{settings.GCS_BACKUP_BUCKET} uchun "
                f"roles/storage.objectAdmin berilganmi? Asl xato: {exc}"
            ) from exc

        if result.local_total == 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  ! {settings.DB_BACKUP_DIR} ichida dump topilmadi. Bu konteynerda "
                    "dbbackups volume mount qilinganmi (celery-worker'da ishga tushiring)?"
                )
            )
            return

        for name in result.uploaded:
            self.stdout.write(
                self.style.SUCCESS(f"  + yuklandi: gs://{settings.GCS_BACKUP_BUCKET}/{name}")
            )
        for name in result.skipped_empty:
            self.stdout.write(self.style.WARNING(f"  ! 0 baytli dump o'tkazib yuborildi: {name}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Tayyor: lokal {result.local_total} ta dump — {len(result.uploaded)} ta "
                f"yuklandi, {result.already} ta allaqachon GCS'da."
            )
        )
