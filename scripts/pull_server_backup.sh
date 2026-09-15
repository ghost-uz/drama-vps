#!/usr/bin/env bash
# ==============================================================================
# Server ko'chishi uchun TO'LIQ tiklash to'plamini lokal diskka tortish.
# LOKAL kompyuterda ishlaydi (Windows: Git Bash; Linux/macOS: bash).
#
#   bash scripts/pull_server_backup.sh                  # root@159.89.100.207
#   bash scripts/pull_server_backup.sh root@<IP>
#   DEST_ROOT=/d/backups/dramauz bash scripts/pull_server_backup.sh
#
# Natija: $DEST_ROOT/<YYYYmmdd-HHMMSS>/  (default DEST_ROOT=~/backups/dramauz)
#   db/drama_db.dump        pg_dump custom format (pg_restore / scripts/restore.sh)
#   db/row_counts.txt       har jadvalning ANIQ qator soni — tiklashdan keyin solishtirish
#   config/.env             prod sozlama va sirlari
#   config/secrets/         GCS service-account kaliti (gcs.json)
#   config/nginx-certs/     Cloudflare Origin CA sertifikati + kaliti
#   config/deploy/          .deploy/{current,previous}_tag + serverdagi git HEAD
#   host/authorized_keys    gh-actions-deploy public kaliti (GitHub SSH_KEY sirining jufti)
#   host/inventory.txt      OS, Docker, ufw, swap, sshd, konteynerlar, sertifikat muddati
#   quiz-bot/               /opt/quiz-bot (kod + .env) va quiz.db (bo'lsa)
#   SHA256SUMS              yuklab olingach lokal tekshiriladi
#
# Serverda BO'LMAGANI uchun olinmaydi: media/static (GCS `cdn.drama.uz`),
# video (Bunny Stream), image (GHCR, public). Redis ATAYLAB olinmaydi — unda
# faqat kesh va Celery broker bor (beat jadvali ham, sessiyalar ham DB'da).
#
# DIQQAT: natijada SIRLAR bor — repo PUBLIC, uni hech qachon commit qilmang.
# Tiklash tartibi: docs/ops/server-migration.md
# ==============================================================================
set -euo pipefail

HOST="${1:-root@159.89.100.207}"
DEST_ROOT="${DEST_ROOT:-$HOME/backups/dramauz}"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_ROOT/$TS"
STAGE="/root/.drama-backup-$TS"   # serverdagi vaqtinchalik papka — oxirida o'chiriladi

ssh_host() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30 "$HOST" "$@"; }

# Sirlar git repo ichiga tushmasin (repo PUBLIC) — serverga tegmasdan oldin tekshiramiz
mkdir -p "$DEST"
if git -C "$DEST" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "!! $DEST git repo ichida — sirlar commit bo'lib ketishi mumkin." >&2
    echo "   DEST_ROOT'ni repo tashqarisiga bering." >&2
    rmdir "$DEST" 2>/dev/null || true
    exit 1
fi

# Serverda sirlarning ortiqcha nusxasi qolmasin — xato bo'lsa ham tozalaymiz
trap 'ssh_host "rm -rf $STAGE" </dev/null >/dev/null 2>&1 || true' EXIT

echo "==> [1/3] Serverda yig'ilmoqda: $HOST:$STAGE"
ssh_host bash -s -- "$STAGE" <<'REMOTE'
set -euo pipefail
STAGE="$1"
umask 077
mkdir -p "$STAGE/db" "$STAGE/config/deploy" "$STAGE/host" "$STAGE/quiz-bot"
cd /opt/drama

# --- DB: to'g'ridan-to'g'ri db konteyneri (pgbouncer orqali EMAS — prod compose izohi).
# Fayl SERVER tomonida yoziladi; tarmoqdagi bayt-aniqlik SHA256SUMS bilan tekshiriladi.
docker exec drama-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
    > "$STAGE/db/drama_db.dump"
# Arxiv o'qiladimi — buzuq dump shu yerda yiqiladi, lokalga yetib bormaydi
docker exec -i drama-db-1 pg_restore --list < "$STAGE/db/drama_db.dump" > /dev/null
# ANIQ qator sonlari (pg_stat n_live_tup taxminiy) — tiklash tekshiruvining etaloni
docker exec -i drama-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq' \
    > "$STAGE/db/row_counts.txt" <<'SQL'
SELECT table_name || '|' || (xpath('/row/c/text()',
       query_to_xml(format('SELECT count(*) AS c FROM public.%I', table_name), false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
SQL

# --- Repo'da YO'Q konfiguratsiya (gitignore'da): sirlar, sertifikatlar, deploy holati
cp -p .env "$STAGE/config/.env"
cp -rp secrets "$STAGE/config/secrets"
cp -rp nginx/certs "$STAGE/config/nginx-certs"
cp -p .deploy/current_tag .deploy/previous_tag "$STAGE/config/deploy/" 2>/dev/null || true
git rev-parse HEAD > "$STAGE/config/deploy/git_head"
git status --short > "$STAGE/config/deploy/git_status"   # server daraxti repo'dan chetlashganmi
cp -p /root/.ssh/authorized_keys "$STAGE/host/authorized_keys"

# --- Host inventari: yangi serverni AYNAN shunday qurish uchun ma'lumotnoma
meta() { curl -s --max-time 3 "http://169.254.169.254/metadata/v1/$1" || true; }
{
    echo "# Server inventari — $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo; echo "## OS / resurslar"
    . /etc/os-release
    echo "$PRETTY_NAME | kernel $(uname -r) | vCPU $(nproc) | RAM $(free -m | awk '/^Mem:/{print $2}') MB"
    df -h / | tail -1
    echo "DigitalOcean: id=$(meta id) region=$(meta region) ip=$(meta interfaces/public/0/ipv4/address)"
    echo; echo "## Docker"
    docker --version
    docker compose version
    docker compose ls
    docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}'
    docker volume ls --format '{{.Name}}'
    echo; echo "## Tarmoq / xavfsizlik"
    ufw status verbose || true
    swapon --show
    sshd -T 2>/dev/null | grep -Ei '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication) ' || true
    echo "authorized_keys:"
    awk '{print "  " $1 " " $NF}' /root/.ssh/authorized_keys
    echo; echo "## Origin sertifikati"
    openssl x509 -in nginx/certs/origin.pem -noout -subject -enddate -ext subjectAltName || true
    echo; echo "## Cron / vaqt zonasi"
    crontab -l || true
    timedatectl show -p Timezone --value || true
} > "$STAGE/host/inventory.txt" 2>&1

# --- quiz-bot (vaqtinchalik imtihon boti, drama'dan mustaqil) — bo'lsa
if [ -d /opt/quiz-bot ]; then
    tar -czf "$STAGE/quiz-bot/opt-quiz-bot.tar.gz" -C /opt quiz-bot
    if [ "$(docker inspect -f '{{.State.Running}}' quiz-bot 2>/dev/null)" = "true" ]; then
        # SQLite backup API — ishlab turgan bazaning izchil nusxasi (oddiy cp yarim yozuvni olishi mumkin)
        docker exec quiz-bot python -c "import sqlite3; s = sqlite3.connect('/data/quiz.db'); d = sqlite3.connect('/tmp/quiz-backup.db'); s.backup(d); d.close(); s.close()"
        docker cp quiz-bot:/tmp/quiz-backup.db "$STAGE/quiz-bot/quiz.db"
        docker exec quiz-bot rm -f /tmp/quiz-backup.db
    fi
fi

cd "$STAGE"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
echo "    serverda yig'ildi: $(du -sh . | cut -f1)"
REMOTE

echo "==> [2/3] Lokalga ko'chirilmoqda: $DEST"
# tar oqimi bayt-aniq; `cd` bilan ochamiz — Windows yo'lidagi `C:` ni tar host deb o'ylamasin
ssh_host "tar -C $STAGE -cf - ." </dev/null | (cd "$DEST" && tar -xf -)

echo "==> [3/3] SHA256 tekshiruvi"
(cd "$DEST" && sha256sum --quiet -c SHA256SUMS)
echo "$TS" > "$DEST_ROOT/LATEST"

echo
echo "==> TAYYOR: $DEST"
echo "    DB dump : $(du -h "$DEST/db/drama_db.dump" | cut -f1), jadvallar: $(wc -l < "$DEST/db/row_counts.txt")"
echo "    Jami    : $(du -sh "$DEST" | cut -f1)"
echo "    Tiklash : docs/ops/server-migration.md"
