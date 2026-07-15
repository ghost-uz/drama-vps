# Drama.uz — DigitalOcean'ga birinchi deploy (EGASI uchun yo'riqnoma)

> Bu hujjat **birinchi marta** production'ga chiqish uchun bosqichma-bosqich
> yo'riqnoma. Texnik mexanika: `docs/ops/deploy.md` (CD), `secret-rotation.md`
> (sirlar), `backup.md`, `monitoring.md`, `bunny.md`, `telegram-bot.md`.
>
> Taxminiy vaqt: **1.5–2 soat**. Xarajat: droplet ~$24/oy.

## Umumiy checklist

- [ ] 1. Sirlarni tayyorlash (GCS kalit, SECRET_KEY, Bunny, Telegram)
- [ ] 2. DigitalOcean droplet yaratish
- [ ] 3. Serverni bazaviy sozlash (Docker, firewall, swap)
- [ ] 4. Cloudflare DNS
- [ ] 5. Loyihani serverga o'rnatish (.env + secrets)
- [ ] 6. GitHub CD sozlash (Actions secrets + GHCR)
- [ ] 7. Birinchi deploy
- [ ] 8. Deploy'dan keyingi MAJBURIY buyruqlar (superuser, 2FA!)
- [ ] 9. Tashqi panellar (Bunny, BotFather, Payme)
- [ ] 10. Yakuniy sinash

---

## 1. Sirlarni tayyorlash (~20 daqiqa)

Eski qiymatlar git tarixiga tushib qolgan (P0-T2) — **rotatsiyasiz chiqmang**.
Har bir yangi qiymatni vaqtincha xavfsiz joyga (parol menejeri) yozib boring —
5-bosqichda `.env` ga kiritasiz.

### 1.1 GCS service-account kaliti (YANGI)

1. [GCP Console](https://console.cloud.google.com) → IAM & Admin →
   Service Accounts → loyiha akkauntini oching → **Keys** tab.
2. Eski `drama-key-v2` kalitni **Delete** qiling (eski kalit tarixda — o'lik bo'lsin).
3. **Add Key → Create new key → JSON** → fayl yuklanadi. Bu faylni 5-bosqichda
   serverga `secrets/gcs.json` nomi bilan qo'yasiz. Kompyuteringizda ham
   repo TASHQARISIDA saqlang.

### 1.2 Django SECRET_KEY (YANGI)

Kompyuteringizda:

```bash
python -c "import secrets; print('django-prod-' + secrets.token_urlsafe(50))"
```

> ⚠️ `get_random_secret_key()` ISHLATMANG — u `$` belgisi qo'shishi mumkin,
> `$` esa Docker Compose `.env` interpolatsiyasini buzadi.

### 1.3 Bunny Stream API kaliti (YANGI)

Bunny dashboard → **Account → API Key → Regenerate**. Yangi qiymatni yozib oling.
Library ID va CDN Hostname o'zgarmaydi (dashboard → Stream → Library).

### 1.4 Telegram bot tokeni (YANGI)

@BotFather → botingizni tanlang → **/revoke** → yangi token beriladi.
`TELEGRAM_ADMIN_CHAT_ID` o'zgarmaydi (bilmasangiz: @userinfobot ga /start).

### 1.5 Tasodifiy tokenlar (yangi yarating)

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Uch marta ishga tushirib, uchta qiymatni yozib oling:
`RopIMcPWKdI-0wn2O6wGmFER50ghz5C4o3U8cMTUooI`, `9dH-CRzebHpG2fb2vuULlORolVIPsbeuG9wqWzU21s4`, `oQV5U1wndRizSiLvqAji2feBvruMO8NrZxKDqYf-e6o` uchun.

---

## 2. DigitalOcean droplet (~10 daqiqa)

Create → Droplets:

| Parametr | Qiymat |
|---|---|
| Region | **Frankfurt (FRA1)** — O'zbekistonga eng yaqin |
| Image | **Ubuntu 24.04 LTS x64** |
| Plan | Basic → Regular → **2 vCPU / 4 GB / 80 GB** (~$24/oy) |
| Authentication | **SSH Key** (yangi yaratsangiz: `ssh-keygen -t ed25519`) |
| Hostname | `drama-prod` |

> Video Bunny CDN'da, rasm/statik GCS'da — 80 GB disk bemalol yetadi.

Yaratilgach **IP manzilni yozib oling** (quyida `<IP>` deb yuritiladi).

---

## 3. Serverni bazaviy sozlash (~10 daqiqa)

```bash
ssh root@<IP>

# Yangilash + Docker
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

# Firewall: faqat SSH va HTTP (SSL'ni Cloudflare tugatadi)
ufw allow OpenSSH
ufw allow 80
ufw --force enable

# 2 GB swap (4 GB RAM'ga sug'urta)
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 4. Cloudflare DNS (~5 daqiqa)

1. DNS → Records: **A** yozuv `drama.uz` → `<IP>`, **Proxied (orange)**.
   `www` uchun ham xuddi shunday A yozuv.
2. SSL/TLS → Overview → rejim: hozircha **Flexible**
   (brauzer↔CF = HTTPS, CF↔server = HTTP:80 — tez start).
   Post-launch'da **Full (strict)** ga o'tkazamiz (origin sertifikat bilan).

---

## 5. Loyihani serverga o'rnatish (~20 daqiqa)

```bash
git clone https://github.com/ghost-uz/drama-vps.git /opt/drama
cd /opt/drama

# GCS kaliti (1.1-bosqichdagi JSON) — nano ochilib, mazmunini joylang:
mkdir -p secrets
nano secrets/gcs.json

# .env
cp .env.example .env
nano .env
```

### `.env` da to'ldiriladigan qiymatlar

| O'zgaruvchi | Qiymat / manba |
|---|---|
| `SECRET_KEY` | 1.2-bosqichdagi yangi qiymat |
| `DEBUG` | `False` |
| `DB_PASSWORD` | Yangi kuchli parol o'ylab toping (birinchi `up`da shu bilan yaratiladi) |
| `TELEGRAM_BOT_TOKEN` | 1.4-bosqichdagi YANGI token |
| `TELEGRAM_ADMIN_CHAT_ID` | O'zingizning chat ID |
| `TELEGRAM_LOGIN_BOT_USERNAME` | Bot @username (masalan `dramauz_bot`, @siz) |
| `BUNNY_STREAM_LIBRARY_ID` | Bunny dashboard → Stream → Library |
| `BUNNY_STREAM_CDN_HOSTNAME` | `vz-....b-cdn.net` (dashboard'dan) |
| `BUNNY_STREAM_API_KEY` | 1.3-bosqichdagi YANGI kalit |
| `BUNNY_STREAM_TOKEN_KEY` | Library → Security → Token Authentication Key |
| `BUNNY_WEBHOOK_SECRET` | 1.5-dagi tasodifiy №1 |
| `PAYME_MERCHANT_ID` / `PAYME_KEY` | Payme merchant kabinetidan |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` (default shunday) |
| `GS_CREDENTIALS_FILE` | `/app/secrets/gcs.json` (konteyner-ichki yo'l — AYNAN shu) |
| `EXTRA_ALLOWED_HOSTS` | `<IP>` (DNS tarqalguncha IP orqali sinash uchun) |
| `IMAGE_NAME` | `ghcr.io/ghost-uz/drama-web` (CD image nomi) |
| `TELEGRAM_BOT_USERNAME` | Foydalanuvchi boti @username |
| `TELEGRAM_WEBHOOK_SECRET` | 1.5-dagi tasodifiy №2 |
| `METRICS_TOKEN` | 1.5-dagi tasodifiy №3 |
| `SITE_URL` | `https://drama.uz` |
| `TMDB_API_KEY` | themoviedb.org → Settings → API (import ishlatilsa) |
| `EMAIL_*` (SMTP) | Bo'lsa to'ldiring; bo'lmasa keyinroq — saytni bloklamaydi |
| `SENTRY_DSN` | Ixtiyoriy (sentry.io) — keyinroq ham qo'shsa bo'ladi |

Qolganlari default qiymatida qolaveradi.

### Bazani ko'tarish

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db redis
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps   # ikkalasi healthy bo'lsin
```

---

## 6. GitHub CD sozlash (~10 daqiqa)

### 6.1 Deploy uchun SSH kalit

Kompyuteringizda YANGI kalit yarating (shaxsiy kalitingizni bermang):

```bash
ssh-keygen -t ed25519 -f deploy_key -N "" -C "gh-actions-deploy"
cat deploy_key.pub   # serverga qo'shiladi
cat deploy_key       # GitHub'ga SSH_KEY sifatida
```

Serverda public keyni qo'shing:

```bash
echo '<deploy_key.pub MAZMUNI>' >> ~/.ssh/authorized_keys
```

### 6.2 GitHub Actions secrets

Repo → Settings → Secrets and variables → **Actions** → New repository secret:

| Secret | Qiymat |
|---|---|
| `SSH_HOST` | `<IP>` |
| `SSH_USER` | `root` |
| `SSH_KEY` | `deploy_key` PRIVATE fayl mazmuni (butunlay) |
| `DEPLOY_PATH` | `/opt/drama` |

### 6.3 Serverda GHCR login (image pull uchun)

GitHub → Settings (profil) → Developer settings → **Personal access tokens
(classic)** → Generate: faqat **`read:packages`** huquqi bilan. Serverda:

```bash
docker login ghcr.io -u ghost-uz    # parol o'rniga PAT
```

---

## 7. Birinchi deploy 🚀

GitHub → **Actions → Deploy → Run workflow** (image_tag bo'sh qoldiring —
commit SHA olinadi). Jarayon: image build → GHCR push → SSH →
`scripts/deploy.sh` (pull → migrate+collectstatic → web → health-gate).

Serverda kuzatish:

```bash
cd /opt/drama
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web
```

**Muvaffaqiyat belgilari:** workflow yashil; `ps` da `web (healthy)`;
`curl -H "Host: drama.uz" http://127.0.0.1/healthz` → `{"status": "ok"}`.

**Chuqurroq tekshiruv (birinchi deploy'da SHART):** `/healthz` — faqat *liveness*
(gunicorn javob beryaptimi, xolos); u DB/Redis'ni TEKSHIRMAYDI va health-gate ham
aynan shunga tayanadi. Ya'ni Redis noto'g'ri sozlangan bo'lsa ham deploy yashil
bo'lishi mumkin. Bog'liqliklar rostdan ulanganini `/readyz` bilan tasdiqlang:

```bash
curl -H "Host: drama.uz" http://127.0.0.1/readyz
# Kutilgan: {"status":"ready","checks":{"database":"ok","cache":"ok","migrations":"ok"}}
```

Biror `check` `down`/`pending` bo'lsa — deploy "yashil" bo'lsa-da, 12-bo'lim
(troubleshooting) bo'yicha o'sha komponentni tuzating.

> Nosozlikda `deploy.sh` avtomatik rollback qiladi — 12-bo'limga qarang.

---

## 8. Deploy'dan keyingi MAJBURIY buyruqlar

```bash
cd /opt/drama
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'

# 1) Admin foydalanuvchi
dc exec web python manage.py createsuperuser

# 2) Admin 2FA — BUSIZ ADMIN'GA KIRA OLMAYSIZ (prod'da default-yoqiq):
dc exec web python manage.py bootstrap_totp <admin-username>
#    Chiqqan otpauth:// URL'ni Google Authenticator'ga qo'shing
#    (ilova: + -> Enter a setup key -> secret'ni kiriting).

# 3) Bunny imzo/referer jonli tekshiruvi
dc exec web python manage.py check_bunny_security
```

---

## 9. Tashqi panellar

| Xizmat | Sozlama |
|---|---|
| **Bunny** | Library → Security → Allowed Referrers: `drama.uz`. ⚠️ "Block no-referrer" YOQMANG (mobil sinadi — docs/ops/bunny.md). Webhook URL: `https://drama.uz/webhooks/bunny/?secret=<BUNNY_WEBHOOK_SECRET>` |
| **@BotFather** | `/setdomain` → `drama.uz` (Telegram login tugmasi uchun) |
| **Bot webhook** | `curl "https://api.telegram.org/bot<TOKEN>/setWebhook" -d url=https://drama.uz/webhooks/telegram/ -d secret_token=<TELEGRAM_WEBHOOK_SECRET>` |
| **Payme** | Merchant kabineti → Endpoint URL: `https://drama.uz/billing/payme/webhook/` |
| **healthchecks.io** | (tavsiya) check oching → ping URL'ni `.env` `HEARTBEAT_URL`ga → `dc up -d celery-beat` qayta |

---

## 10. Admin ichidagi birinchi sozlamalar

1. `https://drama.uz/admin/` → login → 2FA kod.
2. **Kategoriyalar**: Film/Serial kategoriyalariga **Pleyer turi = Klassik**
   qo'ying (Reels kategoriyasi reels'ligicha qoladi).
3. **Obuna rejalari**: Subscription plans bo'sh bo'lsa VIP rejani yarating.
4. Sinov kinosi yarating (yoki TMDB importdan) → video yuklang → publish.

---

## 11. Yakuniy sinash checklisti

- [ ] `https://drama.uz/healthz` → `{"status": "ok"}`
- [ ] Bosh sahifa ochiladi (statik/rasmlar cdn.drama.uz dan yuklanadi)
- [ ] Ro'yxatdan o'tish + login ishlaydi
- [ ] Kino sahifasi: reels-kategoriya → vertikal pleyer; klassik → 16:9 pleyer
- [ ] Video O'YNAYDI (Bunny imzoli URL) — boshqa brauzerda/telefonda ham
- [ ] Admin 2FA bilan kiriladi
- [ ] `curl -H "Authorization: Bearer <METRICS_TOKEN>" https://drama.uz/metrics`
- [ ] Telegram admin-xabari keladi (masalan topup so'rovida)

---

## 12. Muammo bo'lsa (troubleshooting)

| Belgisi | Sababi / davosi |
|---|---|
| Deploy har safar rollback | `dc logs web` — ko'pincha `.env`da xato qiymat. `dc run --rm migrate` xatosini alohida o'qing |
| `DisallowedHost` 400 | IP orqali kiryapsiz — `.env` `EXTRA_ALLOWED_HOSTS=<IP>` borligini tekshiring, `dc up -d web` |
| `GCS kaliti topilmadi:` xatosi | `secrets/gcs.json` bormi? `.env`da `GS_CREDENTIALS_FILE=/app/secrets/gcs.json`mi? |
| `password authentication failed` restart-loop | `.env` paroli o'zgargan, volume eskisida: `docker exec drama-db-1 psql -U drama_user -d drama_db -c "ALTER USER drama_user WITH PASSWORD '<yangi>';"` (docs/ops/secret-rotation.md §2.3) |
| GHCR `denied` pull xatosi | Serverda `docker login ghcr.io` PAT bilan qilinganmi (6.3)? |
| Video 403 | Bunny Token Key noto'g'ri yoki referer cheklovi — `check_bunny_security` |
| Admin'ga kira olmayapman | `bootstrap_totp` bajarilganmi (8-bo'lim)? |
| 520/522 (Cloudflare) | nginx ishlayaptimi: `dc ps`; ufw'da 80 ochiqmi |
| Rollback kerak | `./scripts/rollback.sh` (oldingi muvaffaqiyatli tegga) |

---

## 13. Launch'dan keyingi hafta (shoshilinch emas)

- [x] Cloudflare SSL → **Full (strict)** + Origin Certificate (nginx 443)
      — 2026-07-15 BAJARILDI va jonli tasdiqlandi (`https://drama.uz/` -> 200
      + cf-ray; origin'da `https://localhost/healthz` -> HTTP/2 200 + HSTS).
      Batafsil: `ssl.md`. QOLGAN (ixtiyoriy qattiqlashtirish): origin'ni
      qulflash — ufw'ni Cloudflare IP oralig'iga cheklash va/yoki
      Authenticated Origin Pulls (mTLS). Hozir IP'ni bilgan CF'ni chetlab
      o'tib WAF/rate-limit'ni aylanib o'ta oladi.
- [ ] SMTP (`EMAIL_*`) — parol-reset xatlari uchun
- [ ] `SENTRY_DSN` — xato kuzatuvi
- [ ] `HEARTBEAT_URL` — dead-man monitoring (9-bo'lim)
- [ ] Git tarixini tozalash: `git-filter-repo` (secret-rotation.md §4-6)
- [x] `prod.py`dagi IP yangilandi: `207.154.194.231` -> `159.89.100.207`
      (server ko'chirilgan edi; eski IP repo'da qolib ketgandi)
- [ ] Backup tiklashni BIR MARTA sinab ko'rish (docs/ops/backup.md mashqi)

## 14. Kundalik foydali buyruqlar

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
dc ps                        # holat
dc logs -f web               # web loglari (JSON)
dc logs -f celery-worker     # fon vazifalar
dc exec web python manage.py shell
./scripts/deploy.sh <tag>    # qo'lda deploy
./scripts/rollback.sh        # oldingi versiyaga
dc exec db-backup sh /scripts/backup.sh   # qo'lda backup
```
