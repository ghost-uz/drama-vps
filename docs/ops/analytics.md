# Analitika: nima o'rnatilgan va raqamlarni qanday o'qish [R3-T2]

**Jonli audit sanasi: 2026-11-14** (kod + network tekshiruvi bilan tasdiqlangan).

## Saytda nima bor (va nima YO'Q)

| Asbob | Holat | Izoh |
|---|---|---|
| **Yandex Metrica** `101193995` | ✅ o'rnatilgan | `base.html`da BITTA teg; 1 sahifa = aynan 1 hit (302→200 zanjiri ham bitta hit) |
| **Cloudflare Web Analytics** | ✅ o'rnatilgan (2026-11-14) | cookie'siz beacon; CSP ruxsati bor |
| **GA4** `G-KSPF9LB6Y3` | ❌ saytda YO'Q | akkauntda bor, teg o'rnatilmagan — 0 ma'lumot ("Данные не получены" shundan) |
| **GTM** (5 konteyner) | ❌ saytda YO'Q | jumladan eski www.drama.uz davri konteynerlari; hech biri ulanmagan |

Taqdiri haqida qaror: `docs/adr/` (R3-T1).

## "Bitta odam nechta bo'lib sanaladi?" — YO'Q, sanalmaydi

2026-11 auditi tekshirdi: dublikat teg yo'q, har sahifa-ko'rinish Metrica'da
bitta hit. "Raqamlar shishirilgan" tuyulishining haqiqiy sabablari:

1. **Har asbob MUSTAQIL o'lchaydi** — Metrica, CF va GSC raqamlarini
   QO'SHIB BO'LMAYDI, ular bir hodisaning uch xil ko'rinishi.
2. **visits (tashriflar) ≠ users (foydalanuvchilar)** — bitta odam kuniga
   3 marta kirsa: 1 user, 3 visit, N hit. Doim **"Foydalanuvchilar"**
   ustunini o'qing.
3. **O'z/admin tashriflaringiz ham sanaladi** — filtr qo'yilmaguncha
   (quyida).

## Lug'at — qaysi raqam nimani bildiradi

| Asbob | Ko'rsatkich | Ma'nosi |
|---|---|---|
| Metrica | **Hits (прос­мотры)** | sahifa yuklanishlari |
| Metrica | **Visits (визиты)** | sessiyalar (30 daq tanaffus = yangi visit) |
| Metrica | **Users (посетители)** | cookie bo'yicha unikal brauzerlar |
| CF Web Analytics | **Page views / Visits** | cookie'SIZ baho — Metrica'dan FARQ QILADI va bu normal (metod boshqa; adblocker'lar ham har xil to'sadi) |
| GSC | **Clicks / Impressions** | FAQAT Google qidiruvdan kelganlar — sayt trafigi emas, qidiruv ko'rinishi |

## Egasi uchun Metrica kabinet sozlamalari (bir martalik, ~15 daq)

1. **O'z tashrif filtri:** Настройки → Фильтры → "Не учитывать мои визиты"
   yoki IP bo'yicha filtr (uy/ish IP'laringiz). Kuchga kirgan kundan boshlab
   o'z tashriflaringiz sanalmaydi (orqaga ta'sir qilmaydi).
2. **Maqsadlar (Цели)** — konversiya voronkasi ko'rinishi uchun kamida:
   - `video-start` — JS hodisa (pleyer play bosilganda) yoki sahifa-maqsad
     (kino sahifasiga kirish);
   - `10 daqiqa tomosha` — vaqt-asosli maqsad;
   - `ro'yxatdan o'tish` — `/users/register/` dan keyingi muvaffaqiyat sahifasi;
   - `to'lov sahifasi` — billing sahifasiga kirish.
3. **Hisobot odati:** standart hisobotda "Посетители" (users) + 7-kunlik
   trend; dushanba kunlari bir qarash yetadi.

## CF ↔ Metrica solishtirish (R3-T3, ~2026-11-28)

2 hafta ma'lumot yig'ilgach kun/users/views jadvalini shu faylga qo'shing.
Kutiladigan farq: CF odatda Metrica'dan bir oz BALAND (cookie rad etganlarni
ham ko'radi) yoki PAST (bot-filtri qattiqroq) — ±30% gacha normal, undan
katta uzilish bo'lsa sabab izlanadi.
