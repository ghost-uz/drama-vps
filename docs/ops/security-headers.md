# Xavfsizlik headerlari (ops runbook) [P10-T1]

Barcha headerlar `config/middleware.py` (`SecurityHeadersMiddleware`) va
Django `SecurityMiddleware` (prod.py `SECURE_*`) orqali chiqadi.

## Joriy holat

| Header | Qiymat | Manba |
|--------|--------|-------|
| Content-Security-Policy | allowlist'lar + `frame-ancestors 'self' web.telegram.org…` | middleware |
| X-Frame-Options | `SAMEORIGIN` (eski brauzer fallback; CSP ustun) | prod.py |
| Strict-Transport-Security | 1 yil + subdomains | prod.py |
| X-Content-Type-Options | `nosniff` | prod.py |
| Referrer-Policy | `strict-origin-when-cross-origin` | middleware |
| Permissions-Policy | camera/mic/geo/payment/usb/... o'chiq | middleware |
| Cross-Origin-Opener-Policy | `same-origin-allow-popups` (popup-auth uchun) | base.py |
| Cross-Origin-Resource-Policy | `cross-origin` | middleware |
| X-XSS-Protection | **yuborilmaydi** (deprecated, auditor-abuse xavfi) | — |

## Deploy'dan keyin tekshirish

1. <https://securityheaders.com> da `drama.uz` — maqsad **A**.
2. Telegram tekshiruvi: mobil ilova ichida Mini App ochiladi (nativ WebView —
   frame cheklovi ta'sir qilmaydi) va <https://web.telegram.org> ichida ham
   ishlaydi (frame-ancestors allowlist'da).
3. Yot iframe test: boshqa domendagi sahifada `<iframe src="https://drama.uz">`
   — **bo'sh/bloklangan** bo'lishi kerak (clickjacking yopiq).

## Yangi tashqi resurs (CDN/skript) qo'shganda

`config/middleware.py` dagi tegishli direktivaga host qo'shing (script-src /
style-src / img-src / connect-src / frame-src). Qo'shmasangiz brauzer resursni
JIMGINA bloklaydi (konsolda CSP xatosi) — sahifa "sababsiz" buziladi.

## Texnik qarz — nonce'ga o'tish (P5-T3 bilan)

`script-src` da hozircha `'unsafe-inline'` bor: shablonlarda ~30 inline
event-handler (`onclick=...`) mavjud. Nonce qo'shilsa CSP2 brauzerlar
`'unsafe-inline'`ni e'tiborsiz qoldiradi va handler'lar sinadi. Tartib:

1. P5-T3 (HTMX UX refaktor)da barcha `onclick` → `addEventListener`;
2. inline `<script>` bloklariga `nonce="{{ request.csp_nonce }}"`;
3. middleware'da per-request nonce + `'unsafe-inline'`ni olib tashlash.

`'unsafe-eval'` allaqachon olib tashlangan (yagona `hx-on` ishlatilgan joy
`movie_detail.html` da listener'ga almashtirilgan — hx-on htmx ichida
`new Function` talab qilardi).
