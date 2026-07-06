#!/bin/sh
# ==============================================================================
# Drama.uz PostgreSQL tiklash (restore) [P13-T3] — postgres:16-alpine ichida.
#
#   restore.sh <backup-fayl.dump>
#
# --clean --if-exists: mavjud obyektlarni tiklashdan oldin tozalaydi (toza
# tiklash). DIQQAT: JORIY ma'lumot USTIGA yoziladi — avval ehtiyot backup oling
# yoki staging'da sinang. Tiklash mashqi (drill) protsedurasi: docs/ops/backup.md.
#
# Kerakli env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE.
# ==============================================================================
set -eu

file="${1:-}"
if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "!! Backup fayl topilmadi: '$file'"
    echo "   Ishlatish: restore.sh <backup-fayl.dump>"
    exit 1
fi

echo "==> Tiklash: $file -> $PGDATABASE@$PGHOST"
pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "$PGDATABASE" "$file"
echo "==> Tiklash yakunlandi."
