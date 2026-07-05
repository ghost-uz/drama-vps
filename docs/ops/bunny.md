# Bunny Stream — video xavfsizligi (ops runbook)

## Arxitektura (P2-T4 + P4-T1)

Video manbalar hech qachon ochiq URL sifatida chiqarilmaydi:

- **REST API**: `GET /api/v1/episodes/{id}/playback/` — gating (free 1–10 /
  VIP / funding) tekshiradi, ruxsat bo'lsa **imzolangan** HLS URL qaytaradi.
- **HTML pleyer** (`movie_detail`): xuddi shu gating service; `get_all_urls()`
  endi barcha URL'larni (HLS, MP4, thumbnail, preview, embed) **imzolangan**
  holda beradi.
- Imzo formati — Bunny rasmiy algoritmi:
  `token = base64url(sha256(key + token_path + expires [+ ip] + "token_path=..."))`.
  `token_path = /{video_id}/` (papka) — m3u8 ichidagi segmentlar ham qamraladi.
- iframe embed boshqa format ishlatadi: `SHA256_HEX(key + video_id + expires)`.

`BUNNY_STREAM_TOKEN_KEY` bo'sh bo'lsa URL'lar imzosiz chiqadi (dev/test rejim).

## Token Authentication'ni yoqish (prod)

Tartib MUHIM — teskari qilsangiz video panelda auth yoqilgan, kodda kalit
yo'q holatda butunlay to'xtaydi:

1. **Avval kod deploy qilinadi** (bu repo holati). Imzolangan URL'lar token
   auth hali O'CHIQ zonada ham ishlayveradi (Bunny ortiqcha query param'larni
   e'tiborsiz qoldiradi) — zero-downtime.
2. Bunny panel → **Stream → Library → Security**:
   - **Embed view token authentication** → ON (iframe embed himoyasi);
   - **CDN token authentication** → ON (to'g'ridan HLS/MP4 himoyasi);
   - sahifadagi **Token Authentication Key** ni nusxalang.
3. Serverda `.env` ga `BUNNY_STREAM_TOKEN_KEY=<kalit>` qo'ying, restart.
4. Tekshiruv:
   - sayt pleyeri ishlaydi (token'li URL);
   - `curl https://vz-....b-cdn.net/<video_id>/playlist.m3u8` (imzosiz) →
     **403 qaytishi SHART**.

## Kalit rotatsiyasi

Panel'da kalitni yangilash → `.env` yangilash → restart. Eski token'li URL'lar
darhol o'ladi; maksimal buzilish — foydalanuvchi sahifani bir marta yangilaydi
(pleyer URL'ni qaytadan oladi).

## BUNNY_TOKEN_BIND_IP (default: False)

Token'ni mijoz IP'siga bog'laydi (o'g'irlangan link boshqa IP'da ishlamaydi).
**Yoqishdan oldin o'ylang**: Django ko'rgan IP (CF-Connecting-IP /
X-Forwarded-For) bilan Bunny CDN ko'rgan IP farq qilsa video 403 bo'ladi.
Tipik nomuvofiqliklar:

- sahifa IPv6 orqali, CDN so'rovi IPv4 orqali (dual-stack);
- mobil tarmoq IP rotatsiyasi, CGNAT;
- korporativ proxy/VPN.

Token muddati (`BUNNY_TOKEN_EXPIRY_SECONDS`, default 4 soat) qisqaligi odatda
yetarli himoya; IP-binding faqat ommaviy link-sizish kuzatilganda yoqilsin.

## Referer/hotlink himoyasi (P4-T2)

Token auth linkni MUDDAT bilan cheklaydi; referer cheklovi esa muddati hali
tugamagan imzoli linkni ham boshqa sayt ichiga embed qilishdan to'sadi
(hotlink). Referer'ni soxtalash oson — bu yolg'iz himoya emas, token auth
ustiga qo'shimcha qatlam.

Panel (Stream → Library → Security):

1. **Allowed Referrers** ga qo'shing: `drama.uz`, `*.drama.uz` (staging
   bo'lsa uni ham). Ro'yxat bo'sh = istalgan sayt embed qila oladi.
   Bu ro'yxat CDN (vz-\*.b-cdn.net) va iframe embed'ga birga amal qiladi.
2. **Blocked Referrers** odatda kerak emas (allowlist yetarli).
3. **"Block no-referrer requests"ni YOQMANG** — mobil ilova/native pleyer,
   maxfiylik-rejim brauzerlar va ba'zi Telegram WebView holatlari Referer
   YUBORMAYDI; yoqilsa ular 403 oladi. Asosiy himoya token auth bo'lib
   qolaveradi.

### Sozlamani tekshirish

Jonli tekshiruv (mavjud video GUID bilan, istalgan mashinadan):

    python manage.py check_bunny_security <video_guid>
    python manage.py check_bunny_security <video_guid> --strict   # CI/cron: muammoda exit 1

Buyruq hisoboti: (1) imzosiz URL rad etiladimi — token auth; (2) imzolangan
URL 200mi — kalit mosligi; (3) yot referer (evil.example) bloklanadimi —
hotlink; (4) referersiz so'rov holati — mobil pleyer ta'siri (axborot).

Qo'lda curl bilan:

    # yot referer -> 403 kutiladi
    curl -s -o /dev/null -w "%{http_code}" -e "https://evil.example/" "<imzoli-hls-url>"
    # to'g'ri referer -> 200 kutiladi
    curl -s -o /dev/null -w "%{http_code}" -e "https://drama.uz/" "<imzoli-hls-url>"

## Admin orqali video yuklash (P14-T1)

Oqim (Episode ham, yakka film Movie ham — bitta pipeline):

1. Admin'da video faylni `video_file` maydoniga yuklang (Episode: alohida sahifa
   yoki Movie ichidagi Qismlar tabi; yakka film: Movie -> Media & Vizual tab).
2. Saqlashda status **Yuklanmoqda** bo'ladi, `process_video_upload` (Celery)
   Bunny'da video yaratadi, faylni yuboradi -> **Qayta ishlanmoqda (encoding)**.
3. Encoding tugashi ikki kanaldan keladi: webhook (tez) yoki poll (30s retry).
   Tayyor bo'lganda GUID (`bunny_video_id`) allaqachon bog'langan, status
   **Tayyor**, lokal vaqtinchalik fayl o'chirilgan. GUID'ni qo'lda kiritish
   odatda kerak emas (maydon favqulodda/legacy holat uchun ochiq qoldirilgan).

Fayl validatsiyasi (P10-T3): faqat .mp4/.m4v/.mov/.mkv/.webm/.avi, sehrli-bayt
tekshiruvi bilan, 500 MB gacha (nginx `client_max_body_size` bilan bir xil).

### Muammolarni bartaraf etish (admin action'lar)

- **Xato (FAILED)** yoki tiqilib qolgan yuklash: ro'yxatda belgilab
  **"Bunny'ga qayta yuklash"** — GUID tozalanadi, pipeline noldan yuradi.
  Diqqat: Bunny kutubxonasida chala video yetim qoladi — panel orqali qo'lda
  o'chiriladi (kam uchraydi, avtomatik delete ataylab qo'shilmagan).
  Lokal fayli o'chib bo'lgan (READY) obyektni qayta yuklash uchun avval faylni
  qayta biriktiring.
- **PROCESSING'da tiqilib qolgan** (poll retry'lari ~10 daqiqada tugaydi,
  webhook ham kelmagan bo'lsa status abadiy qoladi): **"Encoding holatini
  Bunny'dan yangilash"** — poll qayta uyg'onadi va holatni sinxronlaydi.

Webhook sozlamasi: Bunny panel -> Stream -> API -> Webhook URL:
`https://drama.uz/webhooks/bunny/?secret=<BUNNY_WEBHOOK_SECRET>`.
