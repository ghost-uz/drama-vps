# Drama.uz — Roadmap va startup bahosi

> **Sana:** 2026-07-10 · **Auditor:** Claude (kod-audit + test-run asosida)
> **Asos:** `drama_tasks.json` (v1: 65 task, 55 done) + `drama-vps-v2_tasks.json` (v2: 32 task, hammasi ochiq) +
> kod auditi (~10.5K satr Python, 42 shablon, 3 ADR, 14 ops-runbook) + jonli tekshiruv:
> **321 test passed / 12 skipped (41s) · coverage 83.8% · ruff toza · mypy 1 xato**.

---

## 1. Baholar (1–100)

| Yo'nalish | Baho | Bir jumlada |
|---|---|---|
| **Texnik arxitektura** | **82 / 100** | Bu bosqichdagi startup uchun kamdan-kam uchraydigan production-intizom; bahoni bitta ochiq xavfsizlik teshigi (repodagi jonli GCS kaliti) va legacy `funding` moduli pastga tortadi. |
| **Foydalanuvchi tajribasi (UX)** | **76 / 100** | Yadro oqimlar (topish → ko'rish → davom ettirish → to'lash) mantiqan to'g'ri va mobil-birinchi qurilgan; retention kanallari (bildirishnoma, hamjamiyat dialogi) va ishonch sahifalari (oferta/maxfiylik) yo'qligi ballni ushlab turibdi. |

### 1.1 Texnik arxitektura — 82 ni nima tashkil qiladi

**Kuchli tomonlar (+):**
- **Majburiy invariantlar servis qatlamida:** har Coin harakati faqat `users/services/wallet.py` (ledger, `select_for_update`, `balance == SUM(amount)`); ko'rish ruxsati faqat `drama/services/playback.py` (HTML view ham, API ham bitta manba). Bu "pul + kontent-qulf" biznesida eng to'g'ri dizayn qarori.
- **Production-infra to'liq:** settings split (base/dev/prod/test), Docker multi-stage + compose (web/db/redis/celery/beat/nginx) + dev/staging/prod override'lar, `/healthz`–`/readyz`, JSON-logging, Sentry (PII o'chiq), CI (lint+mypy+test+build) + zero-downtime CD + backup/restore-drill hujjati.
- **Xavfsizlik posturasi:** imzoli (signed, muddatli) Bunny URL'lar, markazlashgan rate-limit (+429 middleware), CSP `frame-ancestors` allowlist (ALLOWALL tuzatilgan), HSTS, parol siyosati, email-tasdiqlash, upload-validatorlar (image-bomb himoyasi).
- **Test madaniyati:** 321 test (unit + API + Playwright E2E 6 oqim), factory_boy, `assertNumQueries` bilan N+1 qotirilgan, coverage-gate 80%.
- **Hujjatlar:** 14 ops-runbook + 3 ADR — "avtobus omili"ga qarshi haqiqiy himoya.

**Bahoni pastga tortadigan kamchiliklar (−):**
1. [KRITIK] **`drama-key-v2.json` (jonli GCS service-account kaliti) hali ham git'da tracked va tarixda** — SECRET_KEY, DB parol, Bunny API key, Telegram token ham tarixda topilgan (`docs/ops/secret-rotation.md` auditi). Runbook tayyor, lekin rotatsiya bajarilmagan. **Bu yakka o'zi ~8 ball.**
2. [MUHIM] `funding/` app legacy holicha: modelda constraint/indeks yo'q, maqsadga yetganda status avtomatik o'zgarmaydi, refund oqimi yo'q, `funding/tests.py` bo'sh (mantiq bilvosita boshqa testlarda) — P7-T4 ochiq.
3. [MUHIM] Ops bo'shliqlar: metrika/uptime-alert yo'q (P12-T2), admin 2FA + audit-log + gitleaks yo'q (P10-T4), pgbouncer/cursor-pagination yo'q (P9-T3).
4. [O'RTA] CSP'da `script-src 'unsafe-inline'` qolgan (shablonlardagi ~30 inline handler refaktor kutmoqda — hujjatlangan qarz).
5. [O'RTA] Gigiyena: `templates/Untitled-1.html` (25KB, hech qayerda ishlatilmaydi), `e2e/` da manbasiz qolgan `.pyc`, README "Holat" bo'limi eskirgan (P1 3/7 deydi, aslida 55/65), `mypy` 1 xato (`billing/services.py:66`), `movie_detail.html` 46KB monolit.

**82 → 90+ yo'li:** 0-bosqich (sirlar) + P7-T4 + P12-T2 + CSP nonce + shablon dekompozitsiyasi.

### 1.2 UX — 76 ni nima tashkil qiladi

**Kuchli tomonlar (+):**
- **Yadro halqa to'liq va mantiqiy:** bosh sahifa (Davom ettirish → Trend → "Siz ko'rganingiz asosida" → katalog + cheksiz skroll), jonli qidiruv (debounce), faceted explore (son bilan), kino sahifasida pleyer (resume, avto-keyingi, sifat tanlash), mobilda qismlar bottom-sheet.
- **Gating UX to'g'ri qurilgan:** yopiq qism ekranida sabab + kontekstli CTA (funding → "hissa qo'shish" ankor-havola; VIP → "VIP olish") — foydalanuvchi boshi berk ko'chaga kirmaydi.
- **Mobil-birinchi + PWA:** bottom-nav (`aria-current` bilan), o'rnatiladigan manifest, offline sahifa, skip-link, `:focus-visible` — a11y o'ylangan.
- **SEO intizomi kuchli:** JSON-LD (WebSite/VideoObject), OG/Twitter, canonical, video/image sitemap — organik o'sish fundamenti tayyor.
- **Auditoriyaga mos auth:** Telegram login + Google + email-tasdiqlash + parol tiklash.

**Bahoni pastga tortadigan kamchiliklar (−):**
1. [KRITIK] **Retention kanali yo'q:** yangi qism chiqqanda hech kim xabar olmaydi (bildirishnoma markazi bor, lekin asosiy event-manbai yo'q — V2A-T1/T2). Epizodik kontentda bu eng qimmat UX bo'shlig'i.
2. [KRITIK] **Hamjamiyat bir tomonlama:** oddiy foydalanuvchi izohga javob yoza olmaydi (`AddReview` 403, faqat admin) — muhokama, ya'ni qaytib kelish sababi o'lik (V2B-T1).
3. [MUHIM] **Ishonch sahifalari yo'q:** footer'dagi "Qoidalar va Shartlar" havolasi `#` (o'lik); oferta/maxfiylik sahifasi yo'q — pullik xizmat uchun konversiya va huquqiy risk.
4. [MUHIM] **Pleyer janr-standartidan orqada:** subtitr yo'q, intro-skip yo'q, treyler maydoni bor lekin UI'da chiqmaydi (V2E-T1/T2/T3).
5. [O'RTA] To'lovda ishqalanish: Click yo'q (faqat Payme avtomatik), kripto/chek — skrinshot + admin-tasdiq (kutish).
6. [O'RTA] i18n yarim: modeltranslation en-maydonlari bor, lekin `/en/` URL va EN UI yo'q; URL tillari aralash (`janr/`, `inson/` vs `explore/`, `search/`).
7. [O'RTA] Telegram in-app brauzerda qattiq blok-overlay (iOS'dan tashqari) — texnik sabab bor (video WebView'da sinadi), lekin Telegram-markaz auditoriya uchun ishqalanish; overlay matni/yo'nalishi qayta ko'rilishi kerak.

**76 → 85 yo'li:** V2A-T1/T2 (bildirishnoma+bot) + V2B-T1 (dialog) + oferta/maxfiylik + V2E-T1/T2 (subtitr, skip-intro) + V2F-T1 (Click).

---

## 2. Roadmap

> Tartib mantiqiy: avval **xavfsizlik qarzi** (0), keyin **pul yo'lini mustahkamlash** (1), keyin **qaytib kelish sabablari** (2), keyin **o'sish** (3–4). Task ID'lari mavjud tracker'larga ishora qiladi — acceptance-criteria o'sha yerda.

### 0-bosqich — LAUNCH-BLOCKER (shu hafta, ~1 kun + tashqi konsollar)

| # | Ish | Manba | Izoh |
|---|---|---|---|
| 0.1 | **Sirlarni rotatsiya qilish** — GCP'da GCS kalitni almashtirish, SECRET_KEY, DB parol, Bunny key, BotFather token | v1:P0-T2 | `docs/ops/secret-rotation.md` bosqichma-bosqich tayyor. **Faqat egasi bajara oladi** (tashqi konsollar). |
| 0.2 | Kalit faylni git indeksidan untrack qilish + `filter-repo` bilan tarixni tozalash + force-push | v1:P0-T2 | Runbook §3–5; rotatsiyadan KEYIN. Hamkorlar repo'ni qayta klon qiladi. |
| 0.3 | Tez gigiyena: `Untitled-1.html` ni olib tashlash, e2e'dagi yetim `.pyc`, mypy xatosi (`billing/services.py:66`), README "Holat" bo'limini yangilash | audit | ~1 soat, alohida commit. |

### 1-bosqich — Launch hardening (1–2 hafta)

| # | Ish | Manba | Nega hozir |
|---|---|---|---|
| 1.1 | **Crowdfunding hardening:** maqsadga yetganda avto `translating` + bildirishnoma, refund stsenariysi, model constraint/indekslar, `funding/tests.py` to'ldirish | v1:P7-T4 | Pul yo'li — biznes-modelning yuragi; V2F-T5 bunga tayanadi. |
| 1.2 | **Izoh moderatsiya navbati:** report, navbat, ban | v1:P14-T3 | 2-bosqichda hamjamiyat ochiladi (V2B-T1) — moderatsiya OLDIN turishi shart. |
| 1.3 | **Admin 2FA + audit-log + gitleaks CI** | v1:P10-T4 | 0-bosqich saboqlarini qaytarilmas qilish (sir repoga qaytib tushsa CI yiqiladi). |
| 1.4 | **Uptime/metrika + alert** (healthz monitor, xato-darajasi → Telegram) | v1:P12-T2 | Hozir prod "ko'r" rejimda — Sentry bor, lekin uptime/queue-backlog alert yo'q. |
| 1.5 | **Oferta + Maxfiylik sahifalari** + footer o'lik havolani tuzatish | v1:P10-T5 (qisman) | Pullik xizmatga ishonch; to'liq GDPR (eksport/anonimlash) keyinroq. |

### 2-bosqich — Retention to'lqini (3–6 hafta) — *v2 1-to'lqin*

| # | Ish | Manba | Nega hozir |
|---|---|---|---|
| 2.1 | **Yangi-qism bildirishnomasi** (obuna + fan-out, idempotent) | v2:V2A-T1 | Epizodik kontentda retention yadrosi. |
| 2.2 | **Foydalanuvchi Telegram boti** (hisob bog'lash + shaxsiy push) | v2:V2A-T2 | O'zbekiston — Telegram-markaz bozor; eng samarali push-kanal. |
| 2.3 | **User-to-user izoh javoblari** (chuqurlik 1, bildirishnoma bilan) | v2:V2B-T1 | Hamjamiyatni ochadigan eng arzon qulf; 1.2 moderatsiyaga tayanadi. |
| 2.4 | **TMDB import (admin)** | v2:V2D-T1 | Kartochka to'ldirish daqiqalardan soniyalarga — katalog o'sish tezligi. |
| 2.5 | **Click integratsiyasi** | v2:V2F-T1 | Ikkinchi milliy to'lov reli — checkout konversiyasi. |
| 2.6 | Feature-flag tizimi | v2:V2H-T1 | 2–3-bosqich featurelarini xavfsiz, bosqichma-bosqich yoqish uchun oldinga surildi. |

### 3-bosqich — Konversiya va video-UX (2–3 oy)

| # | Ish | Manba |
|---|---|---|
| 3.1 | **Tarjima so'rovlari + ovoz → crowdfunding** (biznes-model yuragi: auditoriya tanlaydi) | v2:V2F-T5 |
| 3.2 | Subtitr (VTT) + intro-skip + treyler UI + pleyer sozlamalari persist | v2:V2E-T1..T4 |
| 3.3 | Gamifikatsiya: kunlik check-in/streak, darajalar/badge, referral | v2:V2C-T1..T3 |
| 3.4 | Izoh reaksiyalari + epizod-izohlar + spoyler himoya + kolleksiyalar | v2:V2B-T2..T4 |
| 3.5 | Bulk epizod yuklash + efir kalendari | v2:V2D-T2/T3 |
| 3.6 | Promo-kod, VIP-sovg'a, Coin-paketlar | v2:V2F-T2..T4 |
| 3.7 | CDN header/cursor-pagination/pgbouncer + kontent scheduling/bulk/preview | v1:P9-T3, P14-T2 |
| 3.8 | Qidiruv analitikasi (zero-result → kontent xaridi signali, 3.1 ga oziq beradi) | v2:V2G-T3 |

### 4-bosqich — Keyinroq / ADR bilan hal qilinadigan

- **EN locale `/en/`** (V2G-T1) — UZ bozor to'yinganda yoki chet auditoriya signali kelganda.
- **Blog/yangiliklar** (V2G-T2) — SEO kontent-marketing.
- **Haftalik email-digest** (V2A-T3), **Web Push ADR** (V2A-T4), **FCM ADR** (V2H-T3), **Watch-party ADR** (V2H-T4).
- **To'liq GDPR** (P10-T5), **admin analitika dashboard** (P14-T4), **kripto-topup avtomatlashtirish** (P7-T3), **GCS orphan tozalash** (V2H-T2), **slug 301-redirect** (V2D-T4 — URL'lar o'zgartirilsa OLDIN shu).

---

## 3. Texnik qarz jurnali (kichik, yig'ilib qolmasin)

1. CSP `script-src 'unsafe-inline'` — inline handler'larni `addEventListener`ga o'tkazib nonce'ga o'tish.
2. `movie_detail.html` (46KB) va `base.html` (29KB) — partial'larga dekompozitsiya; base'dagi yirik inline CSS/JS'ni statikaga chiqarish.
3. `base.html` Telegram-blocker skripti — turkcha izohli ko'chirma; qayta yozish + overlay UX'ini yumshatish.
4. Coverage past nuqtalar: `users/views.py` 74.9%, `users/signals.py` 62.8%.
5. URL tillari aralash (`janr/`, `inson/` vs `explore/`) — o'zgartirilsa faqat V2D-T4 (301-redirect) bilan birga.
6. `funding/models.py` dagi legacy izoh va `Meta` yo'qligi — P7-T4 tarkibida.

## 4. Kuzatiladigan metrikalar (roadmap samarasini o'lchash)

| Metrika | Ta'sir qiluvchi bosqich |
|---|---|
| D1/D7 retention | 2-bosqich (bildirishnoma/bot) |
| Bildirishnoma CTR (bot xabari → tomosha) | 2.1/2.2 |
| Funding konversiyasi (tashrif → hissador) | 1.1, 3.1 |
| Checkout muvaffaqiyat % (boshlangan → to'langan) | 2.5, 3.6 |
| Izoh/DAU (hamjamiyat jonliligi) | 2.3, 3.4 |
| Zero-result qidiruvlar % | 3.8 → 3.1 |
| Xato darajasi / uptime | 1.4 |
