# Server ko'chishi — to'liq backup va yangi VPS'ga tiklash

> **Qachon kerak:** joriy VPS'dan voz kechilganda (provayder yoki tarif
> almashishi, server halokati). Birinchi marta 2026-09-15 da DigitalOcean'dan
> ko'chishga tayyorgarlik sifatida yozilgan; backup va tiklash qismi **amalda
> sinalgan** (1.2-bo'lim).
>
> Taxminiy vaqt: **~1 soat** (server sozlash 15 daq, tiklash 5 daq, deploy +
> DNS + tekshiruv 30 daq). Bog'liq hujjatlar: [`deploy.md`](deploy.md),
> [`launch-runbook.md`](launch-runbook.md), [`backup.md`](backup.md),
> [`ssl.md`](ssl.md), [`domain-migration.md`](domain-migration.md).

## 0. Nima qayerda yashaydi

Server yo'qolganda faqat **serverning o'zida** turgan narsalar yo'qoladi —
qolgani tashqi xizmatlarda:

| Qism | Qayerda | Server o'chsa |
|---|---|---|
| Kod | GitHub `ghost-uz/drama-vps` (**public**) | qoladi |
| Docker image | GHCR `ghcr.io/ghost-uz/drama-web` (**public** — `docker login` shart emas) | qoladi |
| Media + statik | GCS bucket `cdn.drama.uz` | qoladi — ⚠️ Object Versioning **o'chiq** |
| Video | Bunny Stream | qoladi |
| DNS / edge TLS | Cloudflare (`dramauz.com`, `drama.uz` zonalari) | qoladi — A yozuvlar yangilanadi |
| Deploy sirlari | GitHub Actions: `SSH_HOST`, `SSH_USER`, `SSH_KEY`, `DEPLOY_PATH` | qoladi — `SSH_HOST` yangilanadi |
| **PostgreSQL** | `drama_pgdata` volume | **YO'QOLADI** → backup to'plami |
| **`.env`, `secrets/gcs.json`, `nginx/certs/`** | `/opt/drama` (gitignore'da) | **YO'QOLADI** → backup to'plami |
| `.deploy/` (joriy/oldingi teg) | `/opt/drama/.deploy` | yo'qoladi → backup to'plami |
| Redis | `drama_redisdata` volume | ahamiyatsiz: kesh + Celery broker (beat jadvali ham, sessiyalar ham DB'da) |
| quiz-bot | `/opt/quiz-bot` + `quiz-bot_quiz-data` volume | yo'qoladi → backup to'plami |

> ⚠️ **Serverdagi avtomatik backup'larga ishonmang:** 2026-09-15 gacha
> `db-backup` sidecar hech qachon ishga tushmagan (`backup.md`), ishga
> tushganda ham dump'lar **o'sha serverda** saqlanadi. Server ko'chishida
> yagona ishonchli manba — quyidagi lokal to'plam.

**Ikki holat:**

- **Eski server hali tirik:** 2–3-bo'limlar (yangi serverni tayyorlash) →
  eski serverda `dc stop web celery-worker celery-beat` → 1.1 (oxirgi to'plam)
  → 4–7. Shunda dump'dan keyin hech narsa yozilmaydi.
- **Eski server allaqachon o'chgan:** `LATEST` to'plam bilan 2–7. Oxirgi
  to'plamdan keyin yozilgan ma'lumot yo'qolgan bo'ladi.

## 1. Backup to'plami

### 1.1 Olish (eski server ishlayotganda)

Lokal kompyuterda (Windows'da **Git Bash**; PowerShell EMAS — 9-bo'lim):

```bash
cd /c/projects/drama-vps
bash scripts/pull_server_backup.sh              # default: root@159.89.100.207
```

Natija `~/backups/dramauz/<YYYYmmdd-HHMMSS>/` ga yoziladi (repo TASHQARISIDA —
ichida prod sirlari bor, repo esa public), eng so'nggisining nomi
`~/backups/dramauz/LATEST` da. Skript serverdagi xizmatlarga tegmaydi: to'plam
vaqtincha `/root/.drama-backup-*` da yig'iladi va oxirida (xato bo'lsa ham)
o'chiriladi; lokalda SHA256 bilan tekshiriladi.

| Fayl | Mazmuni |
|---|---|
| `db/drama_db.dump` | `pg_dump --format=custom --no-owner --no-privileges` |
| `db/row_counts.txt` | har jadvalning **aniq** qator soni — tiklash etaloni |
| `config/.env` | prod sozlama va sirlari |
| `config/secrets/gcs.json` | GCS service-account kaliti |
| `config/nginx-certs/origin.{pem,key}` | Cloudflare Origin CA (SAN: `dramauz.com`, `*.dramauz.com`, `drama.uz`, `*.drama.uz`; 2041-07-26 gacha) |
| `config/deploy/` | `current_tag`, `previous_tag`, serverdagi `git_head` va `git_status` |
| `host/authorized_keys` | `gh-actions-deploy` + egasining shaxsiy public kalitlari |
| `host/inventory.txt` | OS, Docker, ufw, swap, sshd, konteynerlar, volume'lar |
| `quiz-bot/` | `/opt/quiz-bot` arxivi (kod + `.env`) va `quiz.db` |

> ⚠️ **Server o'chirilishidan OLDIN skriptni OXIRGI MARTA qayta ishga
> tushiring.** Dump'dan keyin yozilgan har bir yangi foydalanuvchi, to'lov
> yoki izoh faqat shu yo'l bilan saqlanadi.

`host/authorized_keys` nega muhim: GitHub'dagi `SSH_KEY` sirining **public
jufti** shu yerda. Uni yangi serverga qo'ysangiz deploy workflow kalitni qayta
yaratmasdan ishlaydi — faqat `SSH_HOST` yangilanadi.

### 1.2 Tiklash mashqi — TASDIQLANGAN (2026-09-15, to'plam `20260915-220942`)

To'plam lokal Docker'da toza `postgres:16-alpine` ga 4-bo'limdagi aynan o'sha
buyruqlar bilan tiklandi:

| Tekshiruv | Natija |
|---|---|
| `pg_restore --exit-on-error` | xatosiz, 4 s |
| Qator sonlari (`row_counts.txt` bilan `diff`) | **67/67 jadval aynan mos**, jami 5369 qator |
| Identity/serial sequence: `last_value >= max(id)` | 64/64 joyida |
| Extension'lar | `pg_trgm 1.6`, `plpgsql` |
| Oxirgi migratsiya | `drama.0039_alter_topslider_options_topslider_movie_and_more` |

Sequence tekshiruvi — ko'chishning klassik tuzog'i: qatorlar tiklanib,
sequence 1 dan boshlansa, birinchi yangi foydalanuvchi `duplicate key` bilan
yiqiladi. Custom-format dump `setval()` ni o'zi tiklaydi — natija shuni
tasdiqlaydi.

### 1.3 Media sug'urta nusxasi (ixtiyoriy)

Media serverda EMAS (GCS), lekin bucket'da versioning o'chiq bo'lgani uchun
bir martalik nusxa olingan: `~/backups/dramauz/gcs-media/media/` (85 fayl,
192 MB — shundan 186 MB `episode_uploads`). Serverni tiklash uchun KERAK EMAS;
faqat bucket yo'qolsa: `gcloud storage cp -r gcs-media/media gs://<bucket>/`.

## 2. Yangi serverni tayyorlash

**Talab:** Ubuntu 24.04 LTS x64, 2 vCPU / 4 GB RAM (joriy stack ~1.4 GB
ishlatadi; 2 GB + swap ham ishlaydi, lekin tor), 25+ GB disk (DB 14 MB,
bitta image 468 MB). Cloudflare oldida turgani uchun region hal qiluvchi
emas — Yevropa (Frankfurt/Helsinki) yetarli.

```bash
ssh -o StrictHostKeyChecking=accept-new root@<YANGI_IP>

apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

# 443 ni ham ANIQ oching: eski serverda ro'yxatda faqat 22/80 bor edi,
# 443 esa Docker ufw'ni CHETLAB o'tgani uchun ishlagan (pastdagi eslatma).
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# 2 GB swap
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

> **Docker va ufw:** Docker publish qilgan portlar (`80`, `443`) iptables'ning
> `DOCKER` zanjiri orqali ufw qoidalaridan OLDIN o'tadi — `ufw deny 443` ularni
> YOPMAYDI. ufw amalda faqat Docker'dan tashqaridagi xizmatni (SSH) himoyalaydi.

### 2.1 SSH kalitlari va qattiqlashtirish

Lokal (Git Bash):

```bash
SNAP=~/backups/dramauz/$(cat ~/backups/dramauz/LATEST)
NEW=root@<YANGI_IP>
ssh $NEW 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && sort -u -o ~/.ssh/authorized_keys ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' < "$SNAP/host/authorized_keys"
```

Kalit bilan kirish **yangi terminalda** ishlashini tekshirgach, parol bilan
kirishni o'chiring (serverda):

```bash
printf 'PasswordAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/00-hardening.conf
sshd -t && systemctl restart ssh
sshd -T | grep -E '^(passwordauthentication|permitrootlogin) '   # no / without-password
```

> ⚠️ **cloud-init tuzog'i:** Ubuntu cloud image'larida
> `sshd_config.d/50-cloud-init.conf` `PasswordAuthentication yes` qo'yishi
> mumkin va u `/etc/ssh/sshd_config` dagi `no` dan USTUN turadi — sshd kalitning
> **birinchi** uchragan qiymatini oladi, `Include` esa faylning boshida.
> Shuning uchun fayl nomi `00-` bilan boshlanadi. Natijani konfig faylni o'qib
> emas, `sshd -T` bilan tekshiring.

## 3. Loyiha va sozlamalarni joylash

Serverda:

```bash
git clone https://github.com/ghost-uz/drama-vps.git /opt/drama
mkdir -p /opt/drama/secrets /opt/drama/nginx/certs /opt/drama/.deploy
```

Lokal (Git Bash):

```bash
scp "$SNAP/config/.env"                   $NEW:/opt/drama/.env
scp "$SNAP/config/secrets/gcs.json"       $NEW:/opt/drama/secrets/gcs.json
scp "$SNAP/config/nginx-certs/origin.pem" "$SNAP/config/nginx-certs/origin.key" $NEW:/opt/drama/nginx/certs/
scp "$SNAP/config/deploy/current_tag" "$SNAP/config/deploy/previous_tag"        $NEW:/opt/drama/.deploy/
```

Serverda:

```bash
cd /opt/drama
chmod 600 .env nginx/certs/origin.key
chmod 644 nginx/certs/origin.pem secrets/gcs.json   # gcs.json konteyner ichidan o'qiladi (ro mount)
# Ixtiyoriy — DNS almashguncha brauzerda to'g'ridan IP orqali sinash uchun:
sed -i 's/^EXTRA_ALLOWED_HOSTS=.*/EXTRA_ALLOWED_HOSTS=<YANGI_IP>/' .env
```

`.env` dagi boshqa hech narsa o'zgarmaydi: `SECRET_KEY` o'sha — tiklangan
sessiyalar amal qiladi (foydalanuvchilar qayta login qilmaydi); `DB_PASSWORD`
o'sha — yangi volume shu parol bilan yaratiladi; `IMAGE_NAME` pin qilingan.

## 4. Bazani tiklash — deploy'dan OLDIN

> **Tartib muhim:** `deploy.sh` `migrate` ni ishga tushiradi. Bo'sh bazada u
> jadvallarni yaratib qo'yadi va keyingi tiklash ular bilan to'qnashadi.
> Shuning uchun: `db` → tiklash → deploy.

Serverda:

```bash
cd /opt/drama
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
dc up -d db redis
dc ps                                  # db: healthy
```

Lokal (Git Bash):

```bash
scp "$SNAP/db/drama_db.dump" "$SNAP/db/row_counts.txt" $NEW:/root/
```

Serverda:

```bash
docker cp /root/drama_db.dump drama-db-1:/tmp/drama_db.dump
docker exec drama-db-1 pg_restore -U drama_user -d drama_db \
    --no-owner --no-privileges --exit-on-error /tmp/drama_db.dump

# Etalon bilan solishtirish — oxirida "MOS" chiqishi SHART
docker exec -i drama-db-1 psql -U drama_user -d drama_db -Atq <<'SQL' | diff /root/row_counts.txt - && echo MOS
SELECT table_name || '|' || (xpath('/row/c/text()',
       query_to_xml(format('SELECT count(*) AS c FROM public.%I', table_name), false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
SQL

docker exec drama-db-1 rm /tmp/drama_db.dump
```

Tiklash yarim yo'lda yiqilsa (faqat **YANGI** serverda!) bazani tozalab qayta
urining: `dc rm -sf db && docker volume rm drama_pgdata && dc up -d db`.
Eski serverda volume o'chirish = ma'lumotni butunlay yo'qotish.

## 5. Birinchi deploy

**A) GitHub Actions orqali (odatiy yo'l)** — lokal kompyuterda:

```bash
gh secret set SSH_HOST -R ghost-uz/drama-vps --body "<YANGI_IP>"
gh workflow run deploy.yml -R ghost-uz/drama-vps --ref main
gh run list -R ghost-uz/drama-vps --workflow deploy.yml -L 1   # keyin: gh run watch <id>
```

`SSH_USER=root`, `SSH_KEY`, `DEPLOY_PATH=/opt/drama` o'zgarmaydi (2.1 da
`authorized_keys` tiklangan).

**B) Serverda qo'lda (tezroq — build'siz, mavjud public image bilan):**

```bash
cd /opt/drama && ./scripts/deploy.sh "$(cat .deploy/current_tag)"
```

Nosozlikda `deploy.sh` `.deploy/current_tag` dagi tegga avtomatik rollback
qiladi (`.deploy/` ham shuning uchun tiklanadi) va endi `db-backup`
sidecar'ini ham ko'taradi.

### 5.1 DNS'dan OLDIN tekshirish

Serverda:

```bash
dc ps                                                              # web: healthy, hammasi Up
curl -s  -H "Host: dramauz.com" http://127.0.0.1/healthz           # {"status": "ok"}
curl -sk --resolve dramauz.com:443:127.0.0.1 https://dramauz.com/readyz
#   {"status":"ready","checks":{"database":"ok","cache":"ok","migrations":"ok"}}
docker exec drama-web-1 python manage.py check_gcs_cors             # "to'liq mos"
```

Lokal kompyuterdan (Cloudflare'ni chetlab, to'g'ridan yangi origin'ga):

```bash
curl -sk --resolve dramauz.com:443:<YANGI_IP> https://dramauz.com/ -o /dev/null -w '%{http_code}\n'   # 200
```

## 6. Cloudflare DNS almashtirish

Ikkala zonada (`dramauz.com` **va** `drama.uz`) DNS → Records → qidiruvga eski
IP `159.89.100.207` ni yozing va chiqqan **hamma** A yozuvni `<YANGI_IP>` ga
almashtiring (Proxied — to'q sariq bulut qolsin). Kutiladiganlar: `dramauz.com`,
`www.dramauz.com`, `drama.uz`, `www.drama.uz` (eski domen va `www` ni nginx
301 qiladi).

- `cdn.drama.uz` ga **TEGMANG** — u GCS'ga qaraydi, serverga emas.
- SSL/TLS rejimi **Full (strict)** qoladi — Origin CA sertifikati IP'ga
  bog'lanmagan, xuddi o'sha fayl ishlaydi.
- Proxied yozuv o'zgarishi edge'da deyarli darhol amal qiladi (TTL kutilmaydi).

## 7. Yakuniy tekshiruv

- [ ] `curl -sI https://dramauz.com/` → `200` + `cf-ray`
- [ ] `https://dramauz.com/readyz` → `ready`
- [ ] `https://drama.uz/` → 301 → `https://dramauz.com/`
- [ ] Kino sahifasida video o'ynaydi (Bunny imzoli URL; `BUNNY_TOKEN_BIND_IP=False`)
- [ ] Admin'ga kirish ishlaydi
- [ ] `docker volume ls | grep dbbackups` bor va qo'lda backup o'tadi:
      `dc exec db-backup sh /scripts/backup.sh`
- [ ] Telegram webhook xatosiz: `curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
      → `last_error_message` yo'q
- [ ] `dc logs --tail 50 celery-beat` va `dc logs --tail 50 celery-worker` — xatosiz
- [ ] Ixtiyoriy tozalash: `config/settings/prod.py` dagi eski IP'ni yangisiga
      almashtirib commit qiling, `.env` dagi `EXTRA_ALLOWED_HOSTS` ni bo'shating
- [ ] **Hammasi ishlagach** yangi serverdan birinchi to'plamni oling:
      `bash scripts/pull_server_backup.sh root@<YANGI_IP>`

## 8. quiz-bot (ixtiyoriy, vaqtinchalik bot)

Bitta token = bitta long-polling iste'molchi: eski nusxa hali ishlasa ikkalasi
`409 Conflict` oladi — avval eskisini to'xtating.

```bash
# lokal (Git Bash)
scp "$SNAP/quiz-bot/opt-quiz-bot.tar.gz" "$SNAP/quiz-bot/quiz.db" $NEW:/root/
# serverda
tar -xzf /root/opt-quiz-bot.tar.gz -C /opt
cd /opt/quiz-bot && docker compose up -d --build
docker cp /root/quiz.db quiz-bot:/data/quiz.db
docker exec -u root quiz-bot chown quiz:quiz /data/quiz.db   # docker cp faylni root egasi bilan yozadi
docker restart quiz-bot
```

## 9. Ma'lum tuzoqlar

| Tuzoq | Oqibat | Yechim |
|---|---|---|
| PowerShell 5.1'da `ssh ... pg_dump > fayl` | binar dump JIM buziladi (native chiqish matn sifatida qayta kodlanadi) | dump'ni serverda faylga yozib `tar`/`scp` bilan oling — skript shunday qiladi |
| Git Bash'da `docker exec ... /tmp/x` | MSYS `/tmp/x` ni `C:/Users/.../Temp/x` ga aylantiradi → konteyner faylni topmaydi | `MSYS_NO_PATHCONV=1`; host yo'lini `cygpath -w` bilan bering |
| Bo'sh bazaga avval deploy | `migrate` jadval yaratadi → tiklash to'qnashadi | 4-bo'lim tartibi: db → tiklash → deploy |
| `.deploy/` tiklanmasa | birinchi deploy nosoz bo'lsa `latest` ga rollback | `.deploy/current_tag` ni ham ko'chiring |
| cloud-init sshd override | parol bilan kirish ochiq qoladi | `00-hardening.conf` + `sshd -T` |
| Docker ufw'ni chetlab o'tadi | `ufw` 80/443 ni yopa olmaydi | origin'ni cheklash kerak bo'lsa: Cloudflare IP allowlist yoki Authenticated Origin Pulls |
| Eski image teglari | eski serverda 20 ta × 468 MB ≈ 9 GB disk | vaqti-vaqti bilan `docker image prune -a --filter "until=720h"` (teglar GHCR'da qoladi) |
