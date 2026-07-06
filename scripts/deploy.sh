#!/bin/sh
# ==============================================================================
# Drama.uz prod deploy [P13-T2] — bir buyruqli, health-gated, avtomatik rollback.
#
#   ./scripts/deploy.sh <IMAGE_TAG>      (masalan git SHA yoki 'latest')
#
# Bosqichlar:
#   1) yangi image'ni pull qiladi;
#   2) migratsiya + collectstatic ALOHIDA bir martalik konteynerda (eski web
#      hali ishlayapti — migratsiyalar backward-compatible bo'lishi SHART);
#   3) web/worker/beat'ni yangi image bilan qayta yaratadi;
#   4) /healthz sog'lom bo'lguncha kutadi — sog'lom bo'lmasa OLDINGI tegga
#      AVTOMATIK rollback qiladi va xato bilan chiqadi.
#
# Rollback KOD (image) ni qaytaradi, SXEMANI EMAS — shu sabab migratsiyalar
# expand/contract (orqaga mos) bo'lishi zarur. Batafsil: docs/ops/deploy.md
# ==============================================================================
set -eu

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
STATE_DIR=".deploy"
CURRENT_TAG_FILE="$STATE_DIR/current_tag"
HEALTH_RETRIES=20
HEALTH_INTERVAL=3

NEW_TAG="${1:-${IMAGE_TAG:-latest}}"
mkdir -p "$STATE_DIR"
PREV_TAG="$(cat "$CURRENT_TAG_FILE" 2>/dev/null || echo latest)"

echo "==> Deploy: $PREV_TAG -> $NEW_TAG"

wait_healthy() {
    # web konteyner sog'ligini (compose healthcheck) kutadi
    cid="$($COMPOSE ps -q web)"
    i=0
    while [ "$i" -lt "$HEALTH_RETRIES" ]; do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)"
        [ "$status" = "healthy" ] && return 0
        i=$((i + 1))
        sleep "$HEALTH_INTERVAL"
    done
    return 1
}

rollback() {
    echo "!! Deploy NOSOZ — $PREV_TAG ga rollback qilinmoqda..."
    IMAGE_TAG="$PREV_TAG" $COMPOSE up -d --no-build web celery-worker celery-beat
    echo "!! Rollback tugadi ($PREV_TAG)."
    exit 1
}

# 1) Yangi image
IMAGE_TAG="$NEW_TAG" $COMPOSE pull

# 2) Migratsiya + collectstatic (ajratilgan, eski web ishlab turgan holda)
if ! IMAGE_TAG="$NEW_TAG" $COMPOSE run --rm migrate; then
    echo "!! Migratsiya muvaffaqiyatsiz — deploy TO'XTATILDI (web tegilmadi)."
    exit 1
fi

# 3) Yangi kodni ishga tushirish
IMAGE_TAG="$NEW_TAG" $COMPOSE up -d --no-build web celery-worker celery-beat

# 4) Sog'liq tekshiruvi — nosozlikda avtomatik rollback
if wait_healthy; then
    echo "$PREV_TAG" > "$STATE_DIR/previous_tag"  # rollback.sh argumentsiz shu tegga qaytadi
    echo "$NEW_TAG" > "$CURRENT_TAG_FILE"
    echo "==> Deploy MUVAFFAQIYATLI: $NEW_TAG"
else
    rollback
fi
