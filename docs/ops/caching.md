# Keshlash strategiyasi (P9-T1)

Backend: Redis (`django_redis`, `KEY_PREFIX=drama`, `IGNORE_EXCEPTIONS=True`
— Redis tushsa sayt keshsiz ishlayveradi). Testlarda LocMem.

## Versiyalangan kalitlar (key-based expiration)

Barcha katalog-hosila kalitlar `catalog:v{n}:...` ko'rinishida
(`drama/cache.py`). Kontent o'zgarganda `bump_catalog_version()` versiyani
+1 qiladi — BITTA atomik INCR bilan hamma katalog keshi (ma'lumot ham,
fragment ham) bir zumda eskiradi; eski kalitlarni Redis LRU o'zi yig'ishtiradi.

| Kalit | Nima | Yozadi | TTL |
|---|---|---|---|
| `catalog:ver` | joriy versiya (int) | bump | muddatsiz |
| `catalog:v{n}:genres/categories/years/countries` | filtr ro'yxatlari | `GenreYearMixin` | 6h |
| `catalog:v{n}:similar:{movie_id}` | o'xshash kino ID'lari | `MovieDetailView` | 6h |
| `catalog:v{n}:trending_tags` | trending teglar | `recompute_trending_tags` / context processor | 24h |
| template fragment (`home_sliders`, `explore_filters` + catalog_ver) | render HTML | `{% cache %}` | 6h |

TTL — zaxira: asosiy invalidatsiya versiya-bump. (Versiya kaliti evict
bo'lsa v1 ga qaytadi — shu TTL'lar tufayli juda eski ma'lumot tirilmaydi.)

## Invalidatsiya manbalari

1. **Signallar** (`drama/signals.py`, `apps.ready()` ulaydi):
   Movie/Episode/Season/Genre/Category/Tag/TopSlider `post_save`+`post_delete`
   hamda `Movie.tags`/`Movie.genres` `m2m_changed` → bump. Movie/Tag
   o'zgarishida `recompute_trending_tags` ham fon'da qayta hisoblanadi.
2. **Qo'lda bump** — `queryset.update()` SIGNAL CHAQIRMAYDI. Joriy ro'yxat:
   - `drama/webhooks.py` (Bunny READY),
   - `drama/tasks.py::publish_scheduled_movies` (beat, bulk publish),
   - `drama/tasks.py::optimize_image_task` (rasm nomi .webp ga almashadi),
   - `drama/admin.py` publish/unpublish action'lari.

   **QOIDA: katalogda ko'rinadigan narsani `.update()` bilan o'zgartirsangiz
   — `bump_catalog_version()` chaqiring.**

## Nima ATAYIN keshlanmaydi

- **To'liq sahifa (cache_page)** — detail'da imzoli video URL'lar IP-bog'liq
  (P4-T1), gating/resume/continue_watching shaxsiy; index'da ham auth
  karusel bor. Anonim "tezlik" section-kesh (ma'lumot+fragment) hisobiga
  keladi, shaxsiylashuv esa har doim jonli (acceptance: kesh aralashmaydi).
- **Reyting ko'rsatkichlari** — `recompute_movie_rating` tez-tez ishlaydi;
  har baho bump qilsa kesh samarasi nolga tushardi. Similar bloki shuning
  uchun ID keshlab, obyektlarni yangi so'rov bilan oladi (reyting/poster
  doim yangi).
- **Kontekst-protsessor natijasini per-request keshlash** — so'rov-sanoq
  testlarini asimmetrik buzadi (eco-platform saboqlari); trending faqat
  Redis kalitidan o'qiladi.

## Yangi kesh qo'shish qoidalari

1. Kalitni `catalog_key()`/`get_or_set_catalog()` orqali yozing (versiya
   avtomatik) va chekli TTL bering.
2. Fragment keshda kalitga `catalog_ver` qo'shing:
   `{% cache 21600 nom catalog_ver %}` (GenreYearMixin kontekstga beradi).
3. Fragment ichida foydalanuvchi-ma'lumot yo'qligiga ishonch hosil qiling
   (username, CSRF token, shaxsiy holat — TAQIQ).
