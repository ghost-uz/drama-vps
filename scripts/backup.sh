#!/bin/sh
# ==============================================================================
# Drama.uz PostgreSQL backup [P13-T3] — postgres:16-alpine ichida ishlaydi
# (db-backup sidecar cron 03:00 UTC yoki `docker compose exec`). Media GCS'da
# (Object Versioning bilan himoyalanadi — docs/ops/backup.md).
#
# Custom format (.dump) — pg_restore uchun (tanlab tiklash, parallel, siqilgan).
# Saqlash siyosati: RETENTION_DAYS kundan eski dump'lar o'chiriladi (lokal).
#
# Off-site (GCS) nusxa BU SKRIPTDA EMAS [R0-T4]: postgres-alpine'da gsutil yo'q
# (eski `command -v gsutil` sharti shu bois JIM o'tib ketardi — hech qachon
# yuklamagan). Endi buni Celery bajaradi: core.tasks.offsite_db_backup_task
# har kuni 08:30 Tashkent (= dumpdan 30 daqiqa keyin) GCS'da yo'q dumplarni
# yuklaydi. Qarang: docs/ops/backup.md "Off-site" bo'limi.
#
# Kerakli env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (postgres image o'qiydi).
# ==============================================================================
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
ts="$(date +%Y%m%d-%H%M%S)"
file="$BACKUP_DIR/drama-$ts.dump"

echo "==> Backup: $PGDATABASE@$PGHOST -> $file"
# `> "$file"` redirect faylni pg_dump ishga tushishidan OLDIN yaratadi. Xatoni
# `set -e` ga topshirsak, skript tozalash satrlariga yetmay o'lardi va 0 baytli
# "dump" ro'yxatda haqiqiy zaxiradek qolardi (eco-platform'da shu bug jangda
# ushlangan). Shuning uchun yiqilishni O'ZIMIZ ushlab, chala faylni o'chiramiz.
if ! pg_dump --format=custom --no-owner --no-privileges "$PGDATABASE" > "$file"; then
    echo "!! pg_dump YIQILDI — chala fayl o'chirilmoqda: $file"
    rm -f "$file"
    exit 1
fi

# Qo'shimcha qalqon: pg_dump 0 qaytarib ham fayl bo'sh bo'lsa (disk/FS holati)
if [ ! -s "$file" ]; then
    echo "!! Backup BO'SH — o'chirilmoqda, xato bilan chiqilmoqda."
    rm -f "$file"
    exit 1
fi
echo "==> Tayyor: $(du -h "$file" | cut -f1)"

# Saqlash siyosati — eski dump'lar
deleted="$(find "$BACKUP_DIR" -name 'drama-*.dump' -mtime +"$RETENTION_DAYS" -print -delete | wc -l)"
[ "$deleted" -gt 0 ] && echo "==> $deleted ta eski dump o'chirildi (> $RETENTION_DAYS kun)"

echo "==> Backup yakunlandi."
