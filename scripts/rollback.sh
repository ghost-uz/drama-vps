#!/bin/sh
# ==============================================================================
# Drama.uz qo'lda rollback [P13-T2] — kodni (image tegini) qaytaradi.
#
#   ./scripts/rollback.sh <IMAGE_TAG>    (qaytariladigan oldingi teg)
#   ./scripts/rollback.sh                (.deploy/previous_tag ni ishlatadi)
#
# DIQQAT: rollback SXEMANI (migratsiyani) qaytarmaydi — migratsiyalar expand/
# contract (orqaga mos) bo'lgani uchun eski kod yangi sxemada ishlayveradi.
# Agar migratsiya buzuvchi bo'lsa (contract fazasi erta qo'llangan), avval DB
# backup'dan tiklang (P13-T3, docs/ops/deploy.md).
# ==============================================================================
set -eu

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
STATE_DIR=".deploy"

TAG="${1:-$(cat "$STATE_DIR/previous_tag" 2>/dev/null || echo)}"
if [ -z "$TAG" ]; then
    echo "!! Rollback tegi berilmadi va .deploy/previous_tag yo'q."
    echo "   Ishlatish: ./scripts/rollback.sh <IMAGE_TAG>"
    exit 1
fi

echo "==> Rollback -> $TAG"
IMAGE_TAG="$TAG" $COMPOSE pull web
IMAGE_TAG="$TAG" $COMPOSE up -d --no-build web celery-worker celery-beat
echo "$TAG" > "$STATE_DIR/current_tag"
echo "==> Rollback tugadi: $TAG"
