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

## Referer/hotlink himoyasi (P4-T2 — keyinroq)

Bunny pull zone'da "Allowed referrers" (drama.uz) sozlash rejalashtirilgan —
alohida task, bu runbook o'shanda to'ldiriladi.
