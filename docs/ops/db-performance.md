# DB so'rov optimizatsiyasi (P9-T2 audit)

## Natijalar — sahifa boshiga so'rovlar (issiq kesh, anonim)

| Sahifa | Oldin (12 karta) | Keyin | Qotirilgan test |
|---|---|---|---|
| Bosh sahifa `/` | ~40 (karta x3 COUNT + bekor prefetch x2 + katalog) | **2** | `test_index_query_count_constant` |
| Explore `/explore/` | ~40 (xuddi shu) | **2** | `test_explore_query_count_constant` |
| Kino detail | 8 + reviewlar soniga qarab o'sardi (avatar/javob N+1) + 3 (epizod re-query) | **8 (doimiy)** | `test_detail_query_count_constant_as_content_grows` |
| Fikrlar sahifasi | 4 + har review'ga profile/javob | **4 (doimiy)** | `test_movie_reviews_page_no_comment_n_plus_one` |

Testlar avval keshni isitadi (birinchi GET), keyin ikkinchi GET'da AYNAN
sonni qotiradi — kontent o'ssa ham son o'zgarmasligi asserted.

## Tuzatilgan naqshlar

1. **Kartadagi `movie.episodes.count`** (x3 har karta) →
   `MovieQuerySet.with_card_data()` = `annotate(live_episode_count=Count("episodes", distinct=True))`.
   `distinct=True` — janr/teg filtri JOIN'lari qatorni ko'paytirganda son buzilmasin.
   QOIDA: movies_card.html ishlatadigan har bir queryset'ga `.with_card_data()` qo'shing.
2. **Ishlatilmaydigan select/prefetch** — index/explore kartasi kategoriya-janr
   ko'rsatmaydi, lekin `prefetch_related("genres","tags")` HAR DOIM 2 so'rov
   bajarardi (prefetch iste'molga qaramay eager). Olib tashlandi.
   QOIDA: prefetch qo'shishdan oldin shablon nimani renderlashini tekshiring.
3. **Prefetch ustida `.filter()/.order_by()`** (detail epizodlari) — prefetch
   keshini chetlab YANGI so'rov ochadi. Endi `Meta.ordering` bilan kelgan
   ro'yxatdan Python'da tanlanadi (aktiv/keyingi qism). Bonus: `?episode=abc`
   ValueError 500 bermaydi.
4. **Komment N+1** — `user__profile` (avatar) select_related + `replies`
   Prefetch (detail va fikrlar sahifasi ikkalasida).
5. **Reverse O2O** — `funding_project` select_related (getattr alohida so'rov edi).
6. **ActorView** — `list()` + `len()` (COUNT so'rovi ortiqcha edi).
7. **Latent bug**: `movie.category.title` — Category'da `title` yo'q (`name`),
   badge hamisha bo'sh chiqardi; so'rov esa ketardi.

## Indekslar (drama 0027)

| Indeks | So'rov shakli | EXPLAIN |
|---|---|---|
| `Movie(country)` | explore filtri `country=?` + davlatlar distinct | `Index Scan using drama_movie_country_562e26_idx` |
| `Review(movie, parent)` | detail/fikrlar `movie=? AND parent IS NULL` | `Index Cond: (movie_id=? AND parent_id IS NULL)` |

Tekshirish usuli (dev ma'lumot oz — planner seq scan tanlashi tabiiy;
indeks YAROQLILIGI `enable_seqscan=off` bilan ko'rsatiladi):

```bash
docker exec drama-db-1 psql -U drama_user -d drama_db \
  -c "SET enable_seqscan=off; EXPLAIN SELECT id FROM drama_movie WHERE country='KR' AND status='published';"
```

## django-debug-toolbar (dev)

`requirements/dev.txt`da bor edi — endi ulangan: `config/settings/dev.py`
(import-guard bilan INSTALLED_APPS+MIDDLEWARE) + `config/urls.py`
(`debug_toolbar_urls()`, faqat DEBUG). Brauzerda istalgan sahifada SQL
paneli — yangi N+1'larni qo'lda ushlash uchun. Prod'ga TA'SIR QILMAYDI
(dev settings + paket prod image'da yo'q).

## Yangi sahifa qo'shganda

- Ro'yxat sahifasi kartali bo'lsa: `.with_card_data()` + faqat shablon
  ishlatadigan select/prefetch.
- Har yangi ro'yxat/detail view'ga issiq-kesh assertNumQueries testi yozing
  (naqsh: drama/tests.py P9-T2 bo'limi).
