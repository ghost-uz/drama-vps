# Domen ko'chishi: `drama.uz` → `dramauz.com`

**Sana:** 2026-07-30 · **Holat:** kod tayyor, deploy bosqichma-bosqich

Bu hujjat ikki narsani qamraydi: (1) ko'chishni **bajarish** tartibi,
(2) qidiruv tizimlari saytni **klon/duplikat deb hisoblamasligi** uchun
qotirilgan invariantlar.

---

## 1. Asosiy tamoyil — nega tartib muhim

Domen ko'chishida eng katta xavf — **ikkala domenning bir vaqtda `200 OK`
qaytarishi**. O'shanda Google ikki mustaqil saytni ko'radi, bir xil kontent
bilan: reyting bo'linadi, biri "asosiy nusxa" deb tanlanadi (odatda eskisi),
ikkinchisi esa nusxa sifatida pastga tushadi.

Yechim — eski domen **hech qachon kontent qaytarmasin**, faqat `301 Moved
Permanently` bilan yangisiga o'tkazsin, **har bir URL o'zining aniq juftiga**.

| Signal | Manba | Fayl |
|---|---|---|
| `canonical` | so'rov xosti | `templates/base.html` |
| `og:url` | so'rov xosti | `templates/base.html` |
| `hreflang` uz/en/x-default | so'rov xosti | `core/templatetags/i18n_urls.py` |
| JSON-LD `WebSite.url` | so'rov xosti | `templates/base.html` |
| `robots.txt` `Sitemap:` / `Host:` | so'rov xosti | `drama/views.py` |
| `sitemap.xml` `<loc>` | **DB `Site` qatori** | `core/migrations/0002_site_domain_dramauz.py` |
| eski domen javobi | `301` | `nginx/ssl.conf` |

> ⚠️ **Eng oson unutiladigan joy — `sitemap.xml`.** U so'rov xostini EMAS,
> `django.contrib.sites` DB qatorini ishlatadi (`SITE_ID = 1`). Qator eski
> domenda qolsa, yangi sayt Google'ga o'zining barcha URL'larini eski domen
> ostida e'lon qiladi. Shu bois u **data-migratsiya** bilan qotirilgan, qo'lda
> emas. Qo'riqchi test: `core/test_domain_migration.py`.

---

## 2. CDN nima uchun `cdn.drama.uz` bo'lib qoladi

GCS bucket nomi custom domen bilan **bir xil bo'lishi shart**, ya'ni CDN'ni
ko'chirish = yangi bucket + barcha statik/media obyektlarni nusxalash.

Bu ATAYLAB qilinmadi: qidiruv tizimlari duplikat-kontentni **sahifa domeni**
bo'yicha baholaydi, asset (rasm/CSS/JS) xosti bo'yicha emas. Ya'ni SEO'ga
ta'siri **nol**. Buning evaziga `drama.uz` DNS zonasi ochiq turishi kerak —
u baribir 301 uchun kerak.

### 2.1 ⚠️ Oqibat: bucket CORS allowlist'i YANGILANISHI SHART

CDN eski zonada qolgani uchun sahifa (`dramauz.com`) va asset (`cdn.drama.uz`)
**har xil origin**. Brauzer resurs turiga qarab har xil qoida qo'llaydi:

| Resurs | CORS kerakmi | Domen ko'chganda |
|---|---|---|
| `<link rel=stylesheet>` CSS | yo'q | ishlayveradi |
| `<script src>` (klassik) | yo'q | ishlayveradi |
| `@font-face` shriftlar | **HA** | **sinadi** |
| `fetch()` / XHR | **HA** | **sinadi** |

Shu bois bu nosozlik **jim** keladi: sayt va admin "ishlayotgandek" ko'rinadi
(CSS ham, JS ham yuklanadi), lekin Unfold admin panelida Inter shrifti va
Material Symbols **ikonkalari** yo'qoladi — ikonkalar o'z ligatura matni
sifatida (`menu`, `search`, `expand_more`) chiqib qoladi.

> 2026-07-31 da AYNAN shu yuz berdi: `config/cors.json` repoda `["*"]` deb
> turgan, lekin bucket'dagi JONLI allowlist `["https://drama.uz",
> "https://www.drama.uz"]` edi — ya'ni repo fayli hech qachon qo'llanmagan.
> Fayl bilan haqiqat orasidagi farqni hech kim ko'rmagan, chunki uni
> qo'llaydigan buyruq ham, tekshiradigan test ham yo'q edi.

Allowlist `config/cors.json` da. Yangi domenni qo'shib, bucket'ga qo'llang
(gcloud SDK shart emas — konteynerda `google-cloud-storage` va kalit bor):

```bash
scp config/cors.json root@159.89.100.207:/tmp/cors.json
ssh root@159.89.100.207 'docker cp /tmp/cors.json drama-web-1:/tmp/cors.json'
ssh root@159.89.100.207 'docker exec -i drama-web-1 python -' <<'PY'
import json
from google.cloud import storage
from google.oauth2 import service_account
creds = service_account.Credentials.from_service_account_file("/app/secrets/gcs.json")
bucket = storage.Client(credentials=creds, project=creds.project_id).get_bucket("cdn.drama.uz")
print("ESKI (rollback uchun saqlang):", json.dumps(bucket.cors))
bucket.cors = json.load(open("/tmp/cors.json"))
bucket.patch(); bucket.reload()
print("YANGI:", json.dumps(bucket.cors, indent=2))
PY
```

> ⚠️ **Repodagi `drama-key-v2.json` ISHLAMAYDI** (`invalid_grant: account not
> found` — kalit rotatsiya qilingan). Amaldagi kalit faqat serverda:
> `/opt/drama/secrets/gcs.json`. Shu sabab buyruq konteyner ichida ishlaydi.

### 2.2 ⚠️ CORS'ni tuzatish YETARLI EMAS — Cloudflare keshini ham tozalang

GCS `Vary: Origin` yuboradi → Cloudflare **har bir origin uchun alohida**
nusxa keshlaydi. Buzuq oynada yangi domendan kelgan har bir so'rov edge'da
`Access-Control-Allow-Origin`**siz** javobni keshlab qo'yadi. Statik obyektlar
esa `Cache-Control: public, max-age=31536000, immutable` — ya'ni bucket
tuzatilgandan keyin ham edge **bir yil davomida** eski buzuq javobni beradi.

Diagnostika: javobda `Vary: Origin` bor, lekin `Access-Control-Allow-Origin`
YO'Q + `cf-cache-status: HIT` va katta `Age:` → bu **keshlangan buzuq javob**,
bucket muammosi emas.

Cloudflare → `drama.uz` zonasi → Caching → Purge Cache → shrift URL'lari
(yoki Purge Everything — hammasi `immutable`, qayta to'ladi).

---

## 3. Bajarish tartibi (ATAYLAB shu ketma-ketlikda)

Har bir qadam oldingisiga bog'liq; tartib buzilsa **uzilish yoki
"ikkala domen 200" oynasi** yuzaga keladi.

### 3.1 Cloudflare: DNS (dramauz.com zonasi)

`dramauz.com` va `www.dramauz.com` → `A 159.89.100.207`, **Proxied (to'q sariq bulut)**.

### 3.2 Cloudflare: SSL rejimi

`SSL/TLS → Overview → Full (strict)`.
`Always Use HTTPS` — yoqilgan.
`HSTS` — **hozircha tegmang**, 3.6 dagi tekshiruvdan keyin yoqiladi.

### 3.3 Server: ikkala domenni qamraydigan Origin CA sertifikati

Hozirgi sertifikat faqat `drama.uz` + `*.drama.uz` ni qamraydi → `dramauz.com`
uchun Cloudflare Full (strict) da TLS handshake yiqiladi va **525** qaytaradi.

**Xususiy kalit serverdan chiqmaydi** — CF'ga faqat CSR beriladi:

```bash
ssh root@159.89.100.207
cd /opt/drama/nginx/certs

openssl req -new -newkey rsa:2048 -nodes \
  -keyout origin-new.key -out origin-new.csr \
  -subj "/CN=dramauz.com" \
  -addext "subjectAltName=DNS:dramauz.com,DNS:*.dramauz.com,DNS:drama.uz,DNS:*.drama.uz"

cat origin-new.csr
```

Cloudflare → **SSL/TLS → Origin Server → Create Certificate** →
*Use my private key and CSR* → CSR'ni joylashtiring → hostnames:
`dramauz.com, *.dramauz.com, drama.uz, *.drama.uz` → 15 yil → **Create**.

Qaytgan sertifikatni serverga yozing va **hali reload qilmang**:

```bash
# CF bergan PEM ni origin-new.pem ga yozing, so'ng:
chmod 600 origin-new.key

# SAN ro'yxatini tasdiqlang (4 ta nom bo'lishi shart)
openssl x509 -in origin-new.pem -noout -ext subjectAltName

# Kalit va sertifikat juftligini tasdiqlang (ikkala hash BIR XIL bo'lsin)
openssl x509 -noout -modulus -in origin-new.pem | openssl md5
openssl rsa  -noout -modulus -in origin-new.key | openssl md5
```

### 3.4 Deploy (kod + sertifikat BIRGA)

Kod (`nginx/ssl.conf` 301 bloklari) va sertifikat **bir vaqtda** faollashishi
kerak:

* faqat sertifikat almashtirilsa → `dramauz.com` eski konfig bilan `200`
  qaytaradi, `drama.uz` ham `200` → **ikkala domen 200** (klon oynasi);
* faqat kod deploy qilinsa → `drama.uz` hali sertifikat qamramagan
  `dramauz.com`ga 301 qiladi → **sayt tushadi**.

```bash
# 1) eski sertifikatni zaxiraga olib, yangisini o'rniga qo'yish
cd /opt/drama/nginx/certs
cp origin.pem origin.pem.bak-drama-uz && cp origin.key origin.key.bak-drama-uz
mv origin-new.pem origin.pem && mv origin-new.key origin.key

# 2) konfigni SINASH (reload'dan OLDIN — noto'g'ri konfig saytni o'chiradi)
cd /opt/drama && git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T nginx nginx -t

# 3) deploy (migrate -> web -> nginx reload) — GitHub Actions orqali
```

`migrate` bosqichi `core.0002_site_domain_dramauz` ni qo'llaydi va `Site`
qatorini yangilaydi.

### 3.5 `.env` (serverda)

```ini
SITE_URL=https://dramauz.com
DEFAULT_FROM_EMAIL=admin@dramauz.com
```

`SITE_URL` — Telegram bot xabarlaridagi va bildirishnomalardagi absolyut
havolalar bazasi. O'zgartirilmasa bot foydalanuvchini eski domenga yuboradi
(u 301 qiladi, lekin ortiqcha sakrash).

### 3.6 Tekshiruv (deploy'dan keyin darhol)

```bash
# yangi domen: 200
curl -sSI https://dramauz.com/ | head -1

# eski domen: 301, aynan shu yo'lga
curl -sSI https://drama.uz/kino/misol/ | grep -iE '^(HTTP|location)'
#   HTTP/1.1 301 ...
#   location: https://dramauz.com/kino/misol/

# www ikkala tomondan ham apex'ga
curl -sSI https://www.drama.uz/    | grep -i location
curl -sSI https://www.dramauz.com/ | grep -i location

# sitemap yangi domenni ko'rsatsin (eski domen UCHRAMASIN)
curl -s https://dramauz.com/sitemap.xml | grep -c 'drama\.uz'   # -> 0
curl -s https://dramauz.com/robots.txt

# webhook yo'llari eski domenda HALI ishlashi kerak (301 EMAS)
curl -sSI https://drama.uz/webhooks/bunny/ | head -1            # -> 405

# CDN CORS (2.1): shrift YANGI domenga ACAO qaytarishi SHART.
# Bo'sh chiqsa -> admin ikonkalari sinadi (jim nosozlik!).
FONT=$(curl -s https://cdn.drama.uz/static/staticfiles.json \
  | tr ',' '\n' | grep -o '"unfold/fonts/material-symbols/[^"]*\.woff2"' \
  | tail -1 | tr -d '"')
curl -sI -H "Origin: https://dramauz.com" "https://cdn.drama.uz/static/$FONT" \
  | grep -iE 'access-control-allow-origin|cf-cache-status|^age:'
#   access-control-allow-origin: https://dramauz.com   <- SHU BO'LISHI KERAK
#   ACAO yo'q + cf-cache-status: HIT + katta Age -> 2.2 (Cloudflare purge)

# ro'yxatda YO'Q origin bloklanishi kerak (allowlist ishlayaptimi)
curl -sI -H "Origin: https://evil.example.com" "https://cdn.drama.uz/static/$FONT" \
  | grep -ci access-control-allow-origin                        # -> 0
```

---

## 4. Google / Yandex (qo'lda, panel orqali)

1. **Search Console → yangi resurs qo'shish**: `https://dramauz.com`.
   Tasdiqlash avtomatik o'tadi — `base.html` dagi `google-site-verification`
   meta-tegi yangi domenda ham chiqadi.
2. **Search Console → eski resurs (`drama.uz`) → Settings → Change of address**
   → `dramauz.com` ni tanlang. **Bu eng muhim qadam**: aynan shu Google'ga
   "bu ko'chish, klon emas" deb rasman aytadi. 301 o'rnatilgan bo'lishi shart,
   aks holda vosita ishlamaydi.
3. Yangi domen uchun `sitemap.xml` va `sitemap-video.xml` ni yuboring.
4. **Yandex Webmaster** → yangi sayt qo'shish → *Перенос сайта / смена
   основного зеркала*.
5. Eski Search Console resursini **o'chirmang** — ko'chish statistikasi
   o'sha yerda ko'rinadi.

> ⏳ 301'ni **kamida 1 yil** saqlang (Google tavsiyasi), imkon bo'lsa doimiy.
> Eski domen o'chsa, unga qaragan barcha tashqi havolalar (backlink) o'ladi.

---

## 5. Tashqi panellar — nazorat ro'yxati

Bularsiz funksiyalar jimgina buziladi. `nginx/ssl.conf` dagi o'tish-davri
istisnolari **aynan shu ro'yxat tugagach** olib tashlanadi.

| # | Panel | Nima o'zgaradi |
|---|---|---|
| 1 | **@BotFather** → `/setdomain` | `dramauz.com` — aks holda Telegram Login widgeti ishlamaydi |
| 2 | **Telegram Bot API** `setWebhook` | `https://dramauz.com/webhooks/telegram/` |
| 3 | **Google Cloud Console** → OAuth client | Authorized redirect URI: `https://dramauz.com/accounts/google/login/callback/` |
| 4 | **Bunny Stream** → webhook | `https://dramauz.com/webhooks/bunny/?secret=...` |
| 5 | **Bunny Stream** → allowed referrers | `dramauz.com` qo'shilsin |
| 6 | **Payme merchant kabineti** | callback URL |
| 7 | **Click merchant kabineti** | Prepare / Complete URL |
| 8 | **Yandex Metrica** | sanoqchi domeni |
| 9 | **Sentry** | allowed domains (ixtiyoriy) |
| 10 | **Uptime monitor** | `https://dramauz.com/healthz` |

Har biri bajarilgach `nginx/ssl.conf` dagi tegishli `location ^~ /webhooks/`,
`/billing/click/`, `/billing/payme/webhook/` istisnolari o'chiriladi va
eski domen **100%** 301 bo'lib qoladi.

---

## 6. Orqaga qaytarish (rollback)

```bash
cd /opt/drama/nginx/certs
cp origin.pem.bak-drama-uz origin.pem && cp origin.key.bak-drama-uz origin.key
cd /opt/drama && git revert <commit> && ./scripts/deploy.sh <oldingi_tag>
```

`Site` qatori uchun migratsiyaning teskarisi bor:

```bash
docker compose ... run --rm migrate python manage.py migrate core 0001_audit_log
```

---

## 7. Ixtiyoriy: Cloudflare edge redirect

Hozir 301 **origin nginx**da (bitta manba — webhook istisnolari bilan birga).
Kelajakda serverni eski domendan butunlay uzmoqchi bo'lsangiz, `drama.uz`
zonasida **Rules → Redirect Rules** qo'shing:

* If: `http.host in {"drama.uz" "www.drama.uz"}`
* Then: `Dynamic` → `concat("https://dramauz.com", http.request.uri)` → **301**

⚠️ `cdn.drama.uz` bu qoidaga **TUSHMASLIGI** shart (u statik/media beradi).
Shuning uchun shart aynan `http.host` bo'yicha, zona bo'yicha emas.
