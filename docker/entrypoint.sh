#!/bin/sh
# ==============================================================================
# Konteyner entrypoint — barcha xizmatlar (web/worker/beat) uchun umumiy.
# Migratsiya va collectstatic FAQAT tegishli env bayroqlari bilan bajariladi
# (RUN_MIGRATIONS=1, COLLECTSTATIC=1), shunda ularni faqat web konteyner
# bajaradi — worker/beat takrorlamaydi (poyga/race oldi olinadi).
# ==============================================================================
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "==> Migratsiyalar qo'llanmoqda..."
    python manage.py migrate --noinput
fi

if [ "${COLLECTSTATIC:-0}" = "1" ]; then
    echo "==> Statik fayllar yig'ilmoqda..."
    python manage.py collectstatic --noinput
fi

echo "==> Ishga tushirilmoqda: $*"
exec "$@"
