#!/bin/sh
# ==============================================================================
# Drama.uz PostgreSQL backup [P13-T3] — postgres:16-alpine ichida ishlaydi
# (db-backup sidecar cron yoki `docker compose exec`). Media GCS'da (Object
# Versioning bilan himoyalanadi — docs/ops/backup.md).
#
# Custom format (.dump) — pg_restore uchun (tanlab tiklash, parallel, siqilgan).
# Saqlash siyosati: RETENTION_DAYS kundan eski dump'lar o'chiriladi.
# GCS_BACKUP_BUCKET berilsa dump off-site (GCS) ga ham nusxalanadi.
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
pg_dump --format=custom --no-owner --no-privileges "$PGDATABASE" > "$file"

# Buzuq/bo'sh dump saqlanib qolmasin — o'lchamni tekshiramiz
if [ ! -s "$file" ]; then
    echo "!! Backup BO'SH — o'chirilmoqda, xato bilan chiqilmoqda."
    rm -f "$file"
    exit 1
fi
echo "==> Tayyor: $(du -h "$file" | cut -f1)"

# Saqlash siyosati — eski dump'lar
deleted="$(find "$BACKUP_DIR" -name 'drama-*.dump' -mtime +"$RETENTION_DAYS" -print -delete | wc -l)"
[ "$deleted" -gt 0 ] && echo "==> $deleted ta eski dump o'chirildi (> $RETENTION_DAYS kun)"

# Off-site nusxa (ixtiyoriy) — gsutil mavjud va bucket berilgan bo'lsa
if [ -n "${GCS_BACKUP_BUCKET:-}" ] && command -v gsutil >/dev/null 2>&1; then
    echo "==> GCS'ga yuklanmoqda: gs://$GCS_BACKUP_BUCKET/db/"
    gsutil cp "$file" "gs://$GCS_BACKUP_BUCKET/db/"
fi

echo "==> Backup yakunlandi."
