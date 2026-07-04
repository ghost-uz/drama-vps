# Frontend build (Tailwind + Alpine + htmx) [P5-T1]

## Stack

- **Tailwind CSS 3** — production build (purge + minify) → `static/css/output.css`
  (~50KB; Play CDN `cdn.tailwindcss.com` OLIB TASHLANGAN — u dev-vosita edi va
  brauzerda runtime kompilyatsiya qilardi).
- **Alpine.js (CSP build)** — `static/js/vendor/alpine-csp.min.js`. CSP'da
  `'unsafe-eval'` yo'qligi uchun ODDIY build ishlamaydi. Komponentlar
  `static/js/app.js` da `Alpine.data()` bilan registratsiya qilinadi;
  shablonda `x-data="dropdown|modal|searchBar"` — inline ifoda EMAS.
- **htmx 1.9.12** — `static/js/vendor/htmx.min.js` (ikkala bazada BIR versiya;
  oldin jsdelivr 1.9.12 + unpkg 1.9.10 aralash edi).

## Buyruqlar

    npm ci                # bog'liqliklar (node 20+)
    npm run build:css     # production CSS (purge+minify)
    npm run watch:css     # dev rejim (fayl o'zgarishida qayta build)

## Qoidalar

1. **`output.css` REPOGA COMMIT QILINADI** — Docker image va CI'da node yo'q
   (P13-T2 da qayta ko'rilishi mumkin). Shablonlarda YANGI Tailwind klass
   ishlatsangiz `npm run build:css` ni qayta ishga tushirib commit qiling,
   aks holda klass prod'da ishlamaydi (purge uni bilmaydi).
2. **Yangi Alpine komponenti** — `static/js/app.js` ga `Alpine.data(...)`
   qo'shiladi (alpine:init ichida). Inline `x-data="{...}"` YOZMANG — CSP
   build uni bajarmaydi.
3. **Vendor yangilash** — `npm i -D paket@versiya`, so'ng dist faylni
   `static/js/vendor/` ga nusxalang (manba: `node_modules/@alpinejs/csp/dist/
   cdn.min.js`, `node_modules/htmx.org/dist/htmx.min.js`).
4. **Ranglar** — `brand`/`dark`/`card`/`drama-green`/`drama-dark`
   `tailwind.config.js` da (base-users Play-CDN inline konfiguratsiyasidan
   ko'chirilgan).

## Cache (prod)

`GS_OBJECT_PARAMETERS = {"cache_control": "public, max-age=86400"}` (prod.py) —
collectstatic GCS'ga yuklaganda obyektlarga 1 kunlik cache header yoziladi
(cdn.drama.uz shuni beradi). Fayl nomlari hash'lanmagani uchun "immutable"
qo'yilmagan; hash'lash (ManifestStaticFilesStorage) — kelajak optimizatsiya.
