# Foydalanuvchi Telegram boti (V2A-T2)

Bot uch ish qiladi: hisob bog'lash (deep-link), yangi-qism push (V2A-T1
fan-out'iga ulangan), /search qidiruv. Admin-xabarnoma kanali (P3-T3,
core/notifications.py) bundan MUSTAQIL — o'sha bot token bo'lishi ham mumkin.

## Sozlash (bir martalik)

1. @BotFather'da bot oching (yoki mavjudini ishlating) — token `.env`
   `TELEGRAM_BOT_TOKEN`da allaqachon bor.
2. `.env` to'ldiring: `TELEGRAM_BOT_USERNAME` (t.me/<shu>), `TELEGRAM_WEBHOOK_SECRET`
   (uzun tasodifiy qiymat), `SITE_URL`.
3. Webhook o'rnating:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d url="https://drama.uz/webhooks/telegram/" \
  -d secret_token="<TELEGRAM_WEBHOOK_SECRET>"
```

Tekshirish: `getWebhookInfo` -> `url` to'g'ri, `last_error_message` bo'sh.

## Oqim

| Bosqich | Nima bo'ladi |
|---|---|
| Sozlamalar -> «Botga ulash» | POST -> 15-daqiqalik BIR MARTALIK token (kesh) -> t.me deep-link redirect |
| Botda `/start <token>` | `Profile.telegram_chat_id` yoziladi, telegram-push yoqiladi |
| Yangi qism READY | V2A-T1 fan-out har ulanmagan userga sayt-ichi, har ulanganiga alohida bot-push task (`rate_limit=20/s`) |
| Foydalanuvchi botni bloklasa | Keyingi push 403 -> `telegram_chat_id` tozalanadi (kanal o'chadi), LOG'da ogohlantirish |
| `/stop` | faqat push o'chadi (ulanish qoladi); `/start` qayta yoqadi |

## Diagnostika

- Push ketmayapti: profil `telegram_chat_id` bormi? `notify_new_episode_telegram=True`mi?
  Celery worker ishlayaptimi (`drama_celery_queue_length` metrikasi)?
- Webhook 403: `TELEGRAM_WEBHOOK_SECRET` setWebhook'dagi bilan bir xilmi?
- Xatolar: worker logida `send_telegram_push_task` ogohlantirishlari + Sentry.
