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

## Kalitlar — qaysi qiymat qayerdan

| `.env` | Bunny panel | Izoh |
|---|---|---|
| `BUNNY_STREAM_LIBRARY_ID` | Stream → (kutubxona) → API → Video Library ID | ommaviy |
| `BUNNY_STREAM_CDN_HOSTNAME` | Stream → (kutubxona) → API → CDN Hostname (`vz-….b-cdn.net`) | ommaviy; CSP shundan avtomatik quriladi |
| `BUNNY_STREAM_API_KEY` | Stream → (kutubxona) → API → **API Key** | **KUTUBXONA kaliti** — Account → API Key EMAS (`video.bunnycdn.com` uni 401 bilan rad etadi) |
| `BUNNY_STREAM_TOKEN_KEY` | Stream → (kutubxona) → Security → Token Authentication Key | imzolash kaliti — VIP gating shunga tayanadi |
| `BUNNY_WEBHOOK_SECRET` | o'zimiz yaratamiz | panel Webhook URL'iga `?secret=` bo'lib qo'yiladi |

Bazada faqat GUID saqlanadi va GUID **kutubxonaga xos** — boshqa hisob/kutubxonaga
o'tilsa kalitlar 4 qator bilan almashadi, lekin videolar O'ZI KO'CHMAYDI
(2026-11-18 yangi hisob: 82 video qayta yuklanishi kerak bo'ldi).

Kalitlar almashgach yangi `.env` faqat qayta YARATILGAN konteynerga tushadi
(db `.env`ni env_file orqali o'qimaydi — `--no-deps` bilan unga tegilmaydi):

    cd /opt/drama
    IMAGE_TAG="$(cat .deploy/current_tag)" docker compose -f docker-compose.yml \
      -f docker-compose.prod.yml up -d --no-build --no-deps --force-recreate \
      web celery-worker celery-beat
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T nginx nginx -s reload

⚠️ Bu buyruqlarni `ssh host 'bash -s' < skript` bilan yuborsangiz, `docker compose
exec` skriptning qolgan qismini stdin'dan "yutib" yuboradi — unga `</dev/null` qo'shing.

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
   - imzosiz URL **ruxsat etilgan referer bilan ham** 403 qaytarishi SHART:
     `curl -s -o /dev/null -w "%{http_code}" -e "https://dramauz.com/" https://vz-....b-cdn.net/<video_id>/playlist.m3u8`
   - ⚠️ Referersiz curl YETARLI EMAS: "Block Direct URL File Access" yoqiq
     bo'lsa referersiz so'rov token auth O'CHIQ bo'lsa ham 403 oladi. 2026-11-18
     da yangi kutubxonada token auth o'chiqligi aynan shu sabab yashiringan
     (`check_bunny_security` ham imzosiz testni referersiz yuborardi — tuzatildi).

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

1. **Allowed Referrers** (Stream'da "Allowed domains") ga qo'shing:
   `dramauz.com`, `*.dramauz.com` (staging bo'lsa uni ham). Ro'yxat bo'sh =
   istalgan sayt embed qila oladi.
   Bu ro'yxat CDN (vz-\*.b-cdn.net) va iframe embed'ga birga amal qiladi.
2. **Blocked Referrers** odatda kerak emas (allowlist yetarli).
3. **"Block Direct URL File Access"ni YOQMANG** (pull zone'dagi nomi "Block
   no-referrer requests") — mobil ilova/native pleyer, maxfiylik-rejim
   brauzerlar va ba'zi Telegram WebView holatlari Referer YUBORMAYDI; yoqilsa
   ular 403 oladi. Asosiy himoya token auth bo'lib qolaveradi.
   **TARTIB:** yoqilgan bo'lsa, uni FAQAT CDN token authentication yoqilib,
   yuqoridagi 4-qadam tekshiruvidan o'tgach o'chiring — aks holda (token o'chiq
   + referersiz ruxsat) videolar butunlay ochiq qoladi.

### Sozlamani tekshirish

Jonli tekshiruv (mavjud video GUID bilan, istalgan mashinadan):

    python manage.py check_bunny_security <video_guid>
    python manage.py check_bunny_security <video_guid> --strict   # CI/cron: muammoda exit 1

Buyruq hisoboti: (1) imzosiz URL ruxsat etilgan referer bilan ham rad
etiladimi — token auth (referer-blok aralashmasligi uchun aynan referer bilan);
(2) imzolangan URL 200mi — kalit mosligi; (3) yot referer (evil.example)
bloklanadimi — hotlink; (4) referersiz so'rov holati — mobil pleyer ta'siri
(axborot).

Qo'lda curl bilan:

    # imzosiz + to'g'ri referer -> 403 kutiladi (token auth)
    curl -s -o /dev/null -w "%{http_code}" -e "https://dramauz.com/" "<imzosiz-hls-url>"
    # yot referer -> 403 kutiladi
    curl -s -o /dev/null -w "%{http_code}" -e "https://evil.example/" "<imzoli-hls-url>"
    # to'g'ri referer -> 200 kutiladi
    curl -s -o /dev/null -w "%{http_code}" -e "https://dramauz.com/" "<imzoli-hls-url>"

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

Webhook sozlamasi: Bunny panel -> Stream -> (kutubxona) -> API -> Webhook URL:
`https://dramauz.com/webhooks/bunny/?secret=<BUNNY_WEBHOOK_SECRET>`.

Webhook `Status` kodlari video obyektining `status` maydonidan FARQLI
([bunny.net/docs/stream/webhooks](https://bunny.net/docs/stream/webhooks)):
3=Finished va 4=Resolution finished → **Tayyor**; 5/8/32 (Failed /
PresignedUploadFailed / VideoDeleted) → **Xato**; 0/1/2/7 → **Qayta
ishlanmoqda**; 6 → **Yuklanmoqda**; 9–13 va 33 (AI subtitr/sarlavha/bob)
holatni O'ZGARTIRMAYDI. Kechikkan "Encoding" tayyor videoni pasaytirmaydi.
Xarita: `drama/webhooks.py`.

Videoni almashtirishda TARTIB: avval admin'da yangi GUID'ni qo'ying, keyin
eski videoni Bunny'dan o'chiring — teskarisida eski GUID uchun kelgan
`32 VideoDeleted` qismni "Xato" qilib qo'yadi (pleyerga ta'sir qilmaydi,
lekin admin yorlig'i chalg'itadi).

## Ko'p ovozli (dublyaj) videolar

Bunny audio trek tilini FAYL metama'lumotidan oladi; yuklangandan keyin
o'zgartirish yo'li hujjatlanmagan. Teglanmagan faylda Bunny har trekka
`LANGUAGE="en"` va `NAME="Audio"` qo'yadi — pleyer bunday takroriy tilga
ishonmaydi va "1-ovoz / 2-ovoz" deb ko'rsatadi (`static/js/player-core.js`).
To'g'ri "O'zbekcha / Inglizcha" uchun yuklashdan OLDIN teglang
(qayta kodlashsiz, tez):

    ffprobe -v error -select_streams a -show_entries stream=index:stream_tags=language,title -of compact kirish.mp4
    ffmpeg -i kirish.mp4 -map 0 -c copy -metadata:s:a:0 language=uzb -metadata:s:a:0 title="O'zbekcha" -metadata:s:a:1 language=eng -metadata:s:a:1 title="English" -disposition:a:0 default -disposition:a:1 0 chiqish.mp4

Til to'g'ri teglangach pleyer o'zbekcha interfeysda o'zbekcha trekni avtomatik
tanlaydi (kaskad: saqlangan til → `<html lang>` → Bunny DEFAULT).
