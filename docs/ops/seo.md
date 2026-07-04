# SEO (ops eslatmalar) [P5-T4]

## Nima chiqadi

- **JSON-LD** (kino sahifasi, `drama/seo.py` da xavfsiz quriladi): serial bo'lsa
  `TVSeries` + aktiv qism `TVEpisode`, yakka film bo'lsa `Movie`; video mavjud
  bo'lsa `VideoObject` (embedUrl = tomosha sahifasi; thumbnail = poster —
  Bunny thumbnail P4-T1'dan beri token-muddatli, Google keshiga YAROQSIZ);
  `BreadcrumbList`. base.html: `WebSite` + `SearchAction`.
- **canonical** — query-parametrsiz (filtr/sahifalash kombinatsiyalari
  duplicate bo'lib indekslanmaydi).
- **hreflang** — FAQAT `uz` + `x-default` (o'ziga ishora, valid pattern).
- **OG/Twitter** meta — har sahifa bloklari; ro'yxat sahifalari (janr/teg/
  qidiruv/katalog) view'dagi `title` kontekstidan unikal `<title>` oladi.

## hreflang'ga `en` qachon qo'shiladi

Faqat en kontent ALOHIDA URL'da xizmat qilganda (`i18n_patterns` +
`LocaleMiddleware`, masalan `/en/...`). Hozir LANGUAGE_CODE=uz va til
almashinuv mexanizmi yo'q — `en`ni bir xil URL'ga ko'rsatish Google'ga
duplicate-content signali bo'lardi. modeltranslation en maydonlari shunda
ishga tushadi.

## Deploy'dan keyin tekshirish

1. <https://search.google.com/test/rich-results> — kino sahifa URL:
   TVSeries/TVEpisode/VideoObject/BreadcrumbList xatosiz.
2. OG preview: Telegram'ga link tashlash yoki <https://www.opengraph.xyz>.
3. `curl -s <kino-url> | grep hreflang` — `uz` + `x-default` (en YO'Q).

## Qoida

Yangi ommaviy sahifa qo'shilsa `{% block page_title %}` +
`{% block meta_description %}` MAJBURIY — aks holda brend-default takrorlanib
"har sahifada unikal title" sharti buziladi.
