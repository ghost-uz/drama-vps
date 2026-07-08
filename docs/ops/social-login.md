# Ijtimoiy login: Google + Telegram (P6-T2)

Foydalanuvchilar Google yoki Telegram orqali bir bosishda kirishi/ro'yxatdan
o'tishi mumkin. Birinchi-tomon (username+parol) login/register O'ZGARMAYDI —
ijtimoiy tugmalar login/register sahifalarida qo'shimcha sifatida chiqadi.

## Arxitektura

| Provayder | Mexanizm | Nega |
|-----------|----------|------|
| **Google** | `allauth.socialaccount.providers.google` (OAuth2) | ID-token JWT tekshiruvi murakkab → yetuk kutubxona ishonchli |
| **Telegram** | Maxsus stdlib HMAC (`users/services/telegram_auth.py`) | Login Widget + Mini App `initData` to'liq nazorat; `SocialAccount` binding |

**Tasdiqlangan identifikator qayerda:** ikkala provayder ham allauth
`SocialAccount` jadvaliga yoziladi (`provider="google"` / `"telegram"`, `uid`).
Bu **avtoritar** manba (unique, foydalanuvchi tahrirlay olmaydi). Telegram uchun
`Profile.telegram_id` faqat **ko'rsatish/bildirishnoma** uchun mirror qilinadi —
u erkin, tahrirlanadigan maydon, shuning uchun auth kaliti bo'la olmaydi.

**Migratsiyasiz:** `socialaccount` jadvallari va `Profile.telegram_id` allaqachon
mavjud → P6-T2 yangi migratsiya qo'shmaydi.

## Sozlama (env)

`.env` ga (namuna: `.env.example`):

```
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_SECRET=...
TELEGRAM_LOGIN_BOT_USERNAME=drama_bot        # bot @username (token EMAS)
TELEGRAM_LOGIN_BOT_TOKEN=                     # bo'sh = TELEGRAM_BOT_TOKEN bilan bir xil
TELEGRAM_LOGIN_MAX_AGE=86400
```

Har bir tugma **faqat** tegishli sozlama berilganda ko'rinadi
(`users/context_processors.py`) — dev'da kalitsiz hech narsa sindirilmaydi.

## Google OAuth ulash (bir marta)

1. https://console.cloud.google.com → loyiha yarating/tanlang.
2. **APIs & Services → OAuth consent screen** → External → ilova nomi + support
   email + logotip; scope'lar: `.../auth/userinfo.email`, `.../auth/userinfo.profile`.
   Prod uchun "Publish app" (aks holda faqat test foydalanuvchilar kira oladi).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   Application type: **Web application**.
   - **Authorized JavaScript origins:** `https://drama.uz`
   - **Authorized redirect URIs:** `https://drama.uz/accounts/google/login/callback/`
     (lokal sinov: `http://localhost:8000/accounts/google/login/callback/`)
4. Client ID / secret'ni `.env` ga (`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_SECRET`).

Kod deploy qilinib, kalitlar berilgach Google tugmasi avtomatik paydo bo'ladi.
DB `SocialApp` yozuvi KERAK EMAS — APP settings orqali beriladi (SITE_ID moslash yo'q).

## Telegram Login Widget ulash (bir marta)

1. @BotFather → botingiz (yoki `/newbot`).
2. `/setdomain` → botni tanlang → **`drama.uz`** (Widget faqat shu domenda ishlaydi).
3. `TELEGRAM_LOGIN_BOT_USERNAME` = bot @username (masalan `drama_bot`).
   `TELEGRAM_LOGIN_BOT_TOKEN` bo'sh qoldirilsa `TELEGRAM_BOT_TOKEN` (bildirishnoma
   boti) ishlatiladi — bitta bot ikkala vazifani bajaraveradi.

Widget `data-auth-url` orqali brauzerni `/users/telegram/login/` ga imzolangan
GET param'lar bilan yo'naltiradi; server HMAC'ni tekshiradi va login qiladi.

### Mini App (Telegram ichidagi WebApp)

Telegram ichida ochilganda front `Telegram.WebApp.initData` ni
`/users/telegram/login/` ga **POST** qiladi (`init_data=...` yoki JSON). Server
`initData` HMAC'ini (`secret = HMAC("WebAppData", token)`) tekshirib
`{"ok": true, "redirect": ...}` qaytaradi. Endpoint kelajakdagi Mini App
frontendi uchun tayyor.

## Xavfsizlik

- **HMAC = autentifikatsiya.** Bot token'siz payload'ni soxtalab bo'lmaydi →
  Telegram endpoint `csrf_exempt` (widget cross-site GET; Mini App fetch).
- **Replay himoyasi:** `auth_date` `TELEGRAM_LOGIN_MAX_AGE` (default 24s) dan eski
  bo'lsa rad etiladi.
- **Rate-limit:** `/users/telegram/login/` 30/min/IP (soxta HMAC / spam hisob).
- **CSP:** widget uchun `script-src telegram.org` + `frame-src oauth.telegram.org`
  (config/middleware.py). Google — to'liq sahifa redirect, CSP o'zgarishi shart emas.
- **Emailsiz hisob:** Telegram foydalanuvchisi email/parolsiz yaratiladi
  (`set_unusable_password`); keyin sozlamalarda email qo'shib parol tiklashi mumkin.

## Tekshirish

- `manage.py check` — allauth/provider yuklanishini tasdiqlaydi.
- Login sahifasi (`/users/login/`) tugmalarni ko'rsatishi (kalitlar berilgan bo'lsa).
- Google: tugma → Google roziligi → qaytishda yangi/mavjud hisobga kirish.
- Telegram: Widget tugmasi → Telegram tasdig'i → hisobga kirish.
- Testlar: `pytest users/test_social_auth.py` (HMAC ikki oqim, binding, throttle,
  Google wiring 302→accounts.google.com).
