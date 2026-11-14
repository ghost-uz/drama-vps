"""core/offsite_backup.py — DB dumplarini GCS'ga off-site sinxronlash [R0-T4].

Kontekst (2026 sentyabr-noyabr falokati saboqlari): kunlik pg_dump'lar faqat
serverning o'zidagi `dbbackups` volume'ida yotardi — server yo'qolsa backuplar
ham birga yo'qoladi. `scripts/backup.sh` dagi eski gsutil tarmog'i esa HECH
QACHON ishlamagan: db-backup sidecar stock postgres:16-alpine, unda gsutil
yo'q, `command -v gsutil` sharti esa bu holni JIM o'tkazib yuborardi.

Yechim arxitekturasi:
  - sidecar faqat LOKAL dump oladi (03:00 UTC, scripts/backup.sh);
  - celery-worker `dbbackups` volume'ini READ-ONLY mount qiladi
    (docker-compose.prod.yml) va shu modul GCS'da YO'Q dumplarni yuklaydi;
  - sinxron IDEMPOTENT (faqat yetishmayotganlar yuklanadi) -> worker bir kun
    o'lik yotsa, ertasiga o'tkazib yuborilganlarini o'zi to'ldiradi;
  - saqlash muddati: lokalda backup.sh RETENTION_DAYS (14 kun), GCS'da bucket
    LIFECYCLE qoidasi (ensure_backup_bucket, default 60 kun).

Nega gsutil/gcloud emas: web image'ida google-cloud-storage allaqachon bor
(CDN uchun), service-account kaliti mount qilingan, celery esa dead-man
heartbeat bilan kuzatuvda [R0-T3]. Sidecar'ga ~1GB gcloud SDK qo'shish yoki
shell'da JWT imzolash o'rniga mavjud, pytest bilan testlanadigan yo'l tanlandi.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from django.conf import settings

if TYPE_CHECKING:  # faqat tip uchun — runtime'da lazy import (dev'da GCS kerak emas)
    from google.cloud import storage

logger = logging.getLogger(__name__)

#: GCS ichidagi prefiks — eski backup.sh xulqi va docs/ops/backup.md bilan mos.
GCS_PREFIX = "db/"
#: db-backup sidecar yozadigan fayl nomi naqshi (scripts/backup.sh bilan juft).
DUMP_PATTERN = "drama-*.dump"


class SyncResult(NamedTuple):
    """Bitta sinxron o'tishining hisoboti (task natijasi / buyruq chiqishi uchun)."""

    uploaded: list[str]  # shu o'tishda GCS'ga yuklanganlar (blob nomlari)
    skipped_empty: list[str]  # 0 baytli (buzuq) lokal dumplar — yuklanmaydi
    already: int  # GCS'da allaqachon bor bo'lgan lokal dumplar soni
    local_total: int  # topilgan lokal dump fayllar soni


def _client() -> "storage.Client":
    """GCS mijozi: prod'da settings.GS_CREDENTIALS (service-account), aks holda ADC."""
    from google.cloud import storage

    credentials = getattr(settings, "GS_CREDENTIALS", None)
    if credentials is not None:
        return storage.Client(credentials=credentials, project=credentials.project_id)
    # Favqulodda/lokal yo'l: GOOGLE_APPLICATION_CREDENTIALS yoki gcloud ADC.
    return storage.Client(project=settings.GS_PROJECT_ID)


def sync_db_backups() -> SyncResult:
    """`DB_BACKUP_DIR` dagi dumplardan GCS'da YO'Qlarini yuklaydi (idempotent).

    - GCS_BACKUP_BUCKET bo'sh -> o'chiq (bo'sh natija, tarmoqqa chiqilmaydi).
    - 0 baytli fayl yuklanMAYDI (backup.sh qalqoni buzilgan holatning izi) —
      hisobotda alohida qaytadi, chaqiruvchi alert berishi uchun.
    - `if_generation_match=0` — "obyekt hali yo'q" oldsharti: parallel ikki
      ishga tushish bir faylni ustma-ust yozolmaydi (poyga -> 412 -> skip).
    """
    bucket_name: str = settings.GCS_BACKUP_BUCKET
    if not bucket_name:
        logger.info("GCS_BACKUP_BUCKET bo'sh — off-site sinxron o'chiq.")
        return SyncResult([], [], 0, 0)

    backup_dir = Path(settings.DB_BACKUP_DIR)
    dumps = sorted(backup_dir.glob(DUMP_PATTERN))
    if not dumps:
        logger.warning("Off-site sinxron: %s ichida %s topilmadi.", backup_dir, DUMP_PATTERN)
        return SyncResult([], [], 0, 0)

    from google.api_core.exceptions import PreconditionFailed

    client = _client()
    bucket = client.bucket(bucket_name)
    existing = {blob.name for blob in client.list_blobs(bucket_name, prefix=GCS_PREFIX)}

    uploaded: list[str] = []
    skipped_empty: list[str] = []
    already = 0
    for dump in dumps:  # eskidan yangiga — uzilishda avval eng eski to'ldiriladi
        if dump.stat().st_size == 0:
            logger.warning("Off-site sinxron: 0 baytli dump o'tkazib yuborildi: %s", dump.name)
            skipped_empty.append(dump.name)
            continue
        blob_name = f"{GCS_PREFIX}{dump.name}"
        if blob_name in existing:
            already += 1
            continue
        try:
            bucket.blob(blob_name).upload_from_filename(str(dump), if_generation_match=0)
        except PreconditionFailed:
            # Poyga: boshqa o'tish allaqachon yuklab bo'lgan — xato emas.
            already += 1
            continue
        logger.info("Off-site sinxron: yuklandi gs://%s/%s", bucket_name, blob_name)
        uploaded.append(blob_name)

    return SyncResult(uploaded, skipped_empty, already, len(dumps))


def ensure_backup_bucket(retention_days: int = 60, location: str | None = None) -> str:
    """Backup bucket'ini tayyorlaydi (idempotent) va qisqa hisobot qaytaradi.

    Yangi bucket: uniform ACL + public access prevention ENFORCED (dumplar PII —
    CDN bucket'dan farqli ravishda PRIVATE!) + `age > retention_days` kunda
    avtomatik o'chirish lifecycle qoidasi (saqlash xarajati chegaralangan).
    Mavjud bucket: lifecycle/PAP yetishmasa to'ldiriladi, borlar o'zgartirilmaydi.

    Kerakli IAM: service-account'da `storage.buckets.create` bo'lmasa (403),
    egasi bucket'ni konsolda yaratib SA'ga `roles/storage.objectAdmin` beradi —
    chaqiruvchi (management buyrug'i) xatoni shu yo'riqnoma bilan o'raydi.
    """
    bucket_name: str = settings.GCS_BACKUP_BUCKET
    if not bucket_name:
        raise ValueError("GCS_BACKUP_BUCKET bo'sh — avval .env'da bucket nomini bering.")

    from google.api_core.exceptions import NotFound
    from google.cloud import storage

    client = _client()
    try:
        bucket = client.get_bucket(bucket_name)
    except NotFound:
        bucket = storage.Bucket(client, name=bucket_name)
        if location is None:
            # Default: CDN bucket qayerda bo'lsa, o'sha joy (yangi qaror kiritmaymiz).
            try:
                location = client.get_bucket(settings.GS_BUCKET_NAME).location
            except Exception:  # noqa: BLE001 — joylashuvni bilib bo'lmasa EU yetarli
                location = "EU"
                logger.warning("CDN bucket joylashuvi o'qilmadi — default EU ishlatiladi.")
        bucket.storage_class = "STANDARD"
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"
        bucket.add_lifecycle_delete_rule(age=retention_days)
        client.create_bucket(bucket, location=location)
        return (
            f"gs://{bucket_name} YARATILDI (location={location}, private, "
            f"lifecycle: {retention_days} kundan keyin o'chadi)."
        )

    fixed: list[str] = []
    if not list(bucket.lifecycle_rules):
        bucket.add_lifecycle_delete_rule(age=retention_days)
        fixed.append(f"lifecycle ({retention_days} kun) qo'shildi")
    if bucket.iam_configuration.public_access_prevention != "enforced":
        bucket.iam_configuration.public_access_prevention = "enforced"
        fixed.append("public access prevention = enforced qilindi")
    if fixed:
        bucket.patch()
        return f"gs://{bucket_name} mavjud edi; {'; '.join(fixed)}."
    return f"gs://{bucket_name} mavjud va sozlamalari joyida."
