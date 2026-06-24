# ADR 0002: API versiyalash strategiyasi — URL path (`/api/v1/`)

- **Holat:** Qabul qilindi (Accepted)
- **Sana:** 2026-06-24
- **Vazifa:** P2-T5 (`drama_tasks.json`)

## Kontekst

drama.uz REST API (P2) mobil ilova, SPA va uchinchi tomon integratsiyalari uchun
mo'ljallangan. Bu klientlar API bilan uzoq muddat ishlaydi; buzuvchi o'zgarish
bo'lganda eski klientlar ishlashdan to'xtamasligi kerak. Versiyalash strategiyasi
zarur.

DRF uch asosiy variantni qo'llab-quvvatlaydi:

1. **URL path** — `/api/v1/movies/`
2. **Accept header** — `Accept: application/json; version=1.0`
3. **Query param** — `/api/movies/?version=1`

## Qaror

**URL path versiyalash: `/api/v1/`.** Barcha endpointlar `/api/v1/` namespace
ostida (`config/api_urls.py`).

## Sabablar

1. **Ko'rinadigan va oddiy** — versiya URL'da aniq; brauzer, curl, Swagger UI'da
   sinash oson. Mobil/integratsiya dasturchilari uchun eng tushunarli.
2. **Keshlash va routing** — proxy/CDN (nginx) URL bo'yicha oson yo'naltiradi va
   keshlaydi; header-versioning kesh kalitini murakkablashtiradi.
3. **drf-spectacular mosligi** — har versiya alohida OpenAPI sxema sifatida toza
   hujjatlanadi.

## Yangi versiya (`v2`) qachon va qanday

- **Qachon:** faqat **buzuvchi** o'zgarish kerak bo'lganda (maydon o'chirish,
  semantika o'zgarishi, majburiy yangi parametr). Qo'shimcha (additive) o'zgarishlar
  — yangi ixtiyoriy maydon yoki endpoint — `v1` ichida qoladi.
- **Qanday:** `config/api_v2_urls.py` + `path("api/v2/", ...)`; `v1` kamida bir
  o'tish davri (6-12 oy) saqlanadi va `Deprecation`/`Sunset` header bilan
  belgilanadi.

## Joriy throttle scope'lari (P2-T5)

| Scope | Limit | Maqsad |
|-------|-------|--------|
| `anon` | 100/soat | Anonim umumiy |
| `user` | 1000/soat | Autentifikatsiyalangan umumiy |
| `review` | 10/soat | Izoh yaratish (spam) |
| `search` | 30/daqiqa | Qidiruv (og'ir ILIKE) |

## Oqibatlar

- **Ijobiy:** oddiy, ko'rinadigan, keshlash-do'st; klientlar versiyani aniq biladi.
- **Salbiy:** versiya almashganda klient URL'ni yangilashi kerak (header-versioning
  shaffofroq bo'lardi) — lekin bu kamdan-kam (faqat buzuvchi o'zgarishda).
