# ADR 0001: Foydalanuvchi modeli — Django `User` + `Profile` saqlanadi

- **Holat:** Qabul qilindi (Accepted)
- **Sana:** 2026-06-24
- **Vazifa:** P1-T7 (`drama_tasks.json`)

## Kontekst

drama.uz ishlab chiqarishda (production) Django'ning standart `auth.User`
modelidan + `users.Profile` (OneToOne kengaytma) dan foydalanadi. `Profile`
qo'shimcha domen maydonlarini saqlaydi: `balance` (Coin), `xp`, `premium`,
avatar va h.k.

Savol (P1-T7): kelajakdagi moslashuvchanlik uchun custom `AUTH_USER_MODEL`
(`AbstractUser`) ga o'tilsinmi, yoki `Profile` pattern yetarlimi?

### Hozirgi bog'liqliklar (risk ko'lami)

`auth.User` ga to'g'ridan-to'g'ri **6 ta foreign key** bog'langan:

| Model | App | Bog'lanish |
|-------|-----|-----------|
| `Profile` | users | OneToOne |
| `TopUpRequest` | users | FK |
| `CryptoTopUpRequest` | users | FK |
| `WatchProgress` | users | FK |
| `Rating` | drama | FK |
| `ActorGift` | drama | FK |

Bundan tashqari Django'ning ichki jadvallari ham `User` ga bog'langan:
`admin.LogEntry`, `auth.Permission` (`user_permissions` M2M), `auth.Group`
(M2M) va sessiyalar.

## Qaror

**Django standart `auth.User` + `Profile` pattern SAQLANADI. Custom
`AUTH_USER_MODEL` ga o'tish RAD ETILADI.**

## Sabablar

1. **Django rasmiy ogohlantirishi.** Jadvallar yaratilgandan keyin
   `AUTH_USER_MODEL` ni o'zgartirish "sezilarli darajada qiyinroq" va rasman
   qo'llab-quvvatlanmaydi. To'g'ri vaqt — loyiha boshi; u bosqich o'tib ketgan.
2. **Yuqori xavf / past foyda.** Prod DB'da `User` jadvalini qayta qurish
   6 FK + Django ichki bog'liqliklarini ko'chirishni talab qiladi; ma'lumot
   yo'qolishi ehtimoli real. `Profile` pattern esa kerakli domen maydonlarini
   allaqachon muammosiz qoplaydi.
3. **Eshik ochiq qoldiriladi.** Barcha migratsiyalar
   `swappable_dependency(settings.AUTH_USER_MODEL)` ishlatadi. Bu ADR doirasida
   modellardagi FK'lar ham `to=settings.AUTH_USER_MODEL` ga ishora qiladigan
   qilib o'zgartirildi (to'g'ridan-to'g'ri `User` import o'rniga). Endi agar
   kelajakda custom User kerak bo'lsa, model qatlami unga tayyor — FK'larni
   qayta yozish shart emas.

> **Eslatma (uslub yaxshilash, migratsiyasiz):** `ForeignKey(User)` va
> `ForeignKey(settings.AUTH_USER_MODEL)` Django'da bir xil migratsiya holatini
> beradi (User swappable bo'lgani uchun), shuning uchun bu o'zgarish yangi
> migratsiya yaratmaydi — faqat kod uslubini best-practice'ga keltiradi.

## Oqibatlar

- **Ijobiy:** ishlab turgan tizimga tegilmaydi; migratsiya xavfi yo'q;
  `Profile` domen mantig'ini auth'dan ajratib turadi (toza chegaralar).
- **Salbiy:** `User` ga to'g'ridan-to'g'ri maydon qo'shib bo'lmaydi (har doim
  `Profile` orqali). Amalda cheklov emas — `Profile` aynan shu maqsadda mavjud.

## Qachon qayta ko'riladi

Quyidagilardan biri yuzaga kelsa, qaror qayta ko'rib chiqiladi:

- `User` autentifikatsiya o'zagini tubdan o'zgartirish kerak bo'lsa (masalan,
  email'ni asosiy identifikator qilish — hozir `Profile`/allauth bilan ham
  hal qilinadi).
- Ma'lumotlar bazasi noldan qayta quriladigan katta migratsiya
  rejalashtirilsa (o'tish narxi shunda amortizatsiya qilinadi).

## Agar kelajakda migratsiya kerak bo'lsa (yuqori darajadagi reja)

1. `users.User(AbstractUser)` yaratish; `AUTH_USER_MODEL = "users.User"`.
2. Eski `auth_user` ma'lumotlarini yangi jadvalga ko'chirish (data migration).
3. 6 FK + M2M (`permissions`/`groups`) + `admin.LogEntry` ni yangi modelga ulash.
4. To'liq backup + staging'da repetitsiya; **qaytarib bo'lmaydigan** amal
   sifatida ko'rib chiqish.
