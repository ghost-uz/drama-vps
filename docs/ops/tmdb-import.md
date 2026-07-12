# TMDB metadata import (V2D-T1)

Admin: **Kinolar ro'yxati -> «TMDB'dan import»** tugmasi. Qidiruv qutisiga nom,
raqamli TMDB ID (`71712`), `tv/71712` yoki to'liq themoviedb.org havolasi
kiritiladi; natijadan «Import» bosilganda **qoralama (draft)** Movie yaratiladi.

## Sozlash

1. [themoviedb.org](https://www.themoviedb.org/settings/api) hisobida API kalit
   oling. `.env`ga yozing — ikkala format ham ishlaydi:
   - v3 kalit (qisqa hex) -> `api_key` query-param bilan yuboriladi;
   - v4 Read Access Token (`eyJ...`) -> `Authorization: Bearer`.
2. `TMDB_LANGUAGE` — metadata tili (default `en-US`; `ru-RU` mumkin). K-drama
   nomlari uz tilida deyarli yo'q — qoralamani staff tarjima qiladi.

## Nima import qilinadi

| Manba | Maydon |
|---|---|
| name/title, original_name/original_title | title, original_title |
| overview, tagline | description, tagline |
| first_air_date / release_date | year |
| origin_country / production_countries | country (lokal nom, `COUNTRY_MAP`) |
| genres | Genre M2M (`TMDB_GENRE_MAP` jadvali; yo'q ID o'tkazib yuboriladi) |
| episode_run_time / runtime | duration |
| number_of_episodes | episodes_count (film = 1) |
| credits.cast (birinchi 10) | Actor get_or_create (dedup: original_name/name), 5 tasi main_actors |
| poster_path, profile_path | poster + aktyor rasmlari — **fonda** (Celery) |

Import ikki bosqichli: metadata **sinxron** (xato darhol ko'rinadi), rasmlar
**Celery**da (`tmdb_download_images`, tarmoq xatosida 3x retry, idempotent).
Dublikat himoyasi: `Movie.tmdb_id` unique (`tv/71712` ko'rinishida saqlanadi).
Slug to'qnashsa `-yil` suffiksi qo'shiladi (`vincenzo-2021`).

## Huquqiy eslatma (poster/rasmlar)

- TMDB shartlariga ko'ra xizmatdan foydalanganda attribution talab qilinadi:
  *"This product uses the TMDB API but is not endorsed or certified by TMDB."*
  Sayt haqida sahifasida ko'rsatilishi kerak.
- **Poster/kadr rasmlarining mualliflik huquqi TMDB'ga emas, distribyutor/
  studiyaga tegishli.** TMDB API ularni "fair use" kafolatisiz beradi — nashr
  etishdan oldin kontent litsenziyangiz rasmlarni ham qamrashini tekshiring.
  Import faqat ma'lumot kiritishni tezlashtiradi; huquqiy javobgarlik
  platformada qoladi.

## Diagnostika

- «TMDB_API_KEY sozlanmagan» — `.env` to'ldirilmagan.
- 401 — kalit noto'g'ri; 429 — so'rov chegarasi, birozdan keyin.
- Rasm kelmadi: Celery worker ishlayaptimi? Worker logida
  `tmdb_download_images` ogohlantirishlari; task idempotent — kino change
  sahifasini saqlamasdan qayta chaqirsa bo'ladi (yoki qo'lda poster yuklang).
- Sof raqamli qidiruv avval ID deb sinaladi; topilmasa nom sifatida qidiriladi.
