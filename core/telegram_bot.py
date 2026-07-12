"""core/telegram_bot.py — foydalanuvchi Telegram boti [V2A-T2].

Uch vazifa:
  1. Hisob bog'lash: sayt Sozlamalarida token yaratiladi (make_link_token,
     keshda 15 min, BIR MARTALIK) -> t.me deep-link -> /start <token> ->
     Profile.telegram_chat_id yoziladi. Chat ID shu yo'l bilan KELGANI uchun
     botning yozish huquqi kafolatlangan (foydalanuvchi Start bosgan).
  2. Buyruqlar: /start, /stop (push o'chirish), /search (FTS servisdan).
  3. Webhook view: setWebhook secret_token'i X-Telegram-Bot-Api-Secret-Token
     header'ida tekshiriladi; ichki xatolarda ham 200 — Telegram bir xil
     update'ni qayta-qayta urib "retry bo'roni" qilmasin (xato LOG'da).

Long-poll EMAS, webhook: prod'da doimiy ochiq HTTPS bor (Cloudflare) va
webhook qo'shimcha jarayon talab qilmaydi. Sozlash: docs/ops/telegram-bot.md.
Admin-xabarnoma kanali (core/notifications.py) bundan mustaqil qoladi.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

LINK_TOKEN_TTL = 15 * 60  # deep-link token muddati [AC-1]
_LINK_PREFIX = "tg-link:"
_API_TIMEOUT = 10

HELP_TEXT = (
    "Buyruqlar:\n"
    "/search <nom> — serial qidirish\n"
    "/stop — yangi-qism xabarlarini o'chirish\n"
    "/start — xabarlarni qayta yoqish"
)


class TelegramBlocked(Exception):
    """Foydalanuvchi botni bloklagan (HTTP 403) — push kanalini o'chirish signali."""


# --- Bot API qatlami ---


def call_api(method: str, payload: dict) -> dict:
    """Telegram Bot API chaqiruvi; 403 -> TelegramBlocked, boshqa xato -> raise."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    resp = requests.post(url, json=payload, timeout=_API_TIMEOUT)
    if resp.status_code == 403:
        raise TelegramBlocked(f"chat bloklangan: {payload.get('chat_id')}")
    resp.raise_for_status()
    return resp.json()


def send_message(chat_id: int, text: str) -> dict:
    return call_api(
        "sendMessage",
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
    )


# --- Deep-link bog'lash tokeni ---


def make_link_token(user_id: int) -> str:
    """Bir martalik, muddatli token yaratib keshga yozadi [AC-1]."""
    token = secrets.token_urlsafe(24)  # 32 belgi — t.me start parametri 64 limitida
    cache.set(_LINK_PREFIX + token, user_id, LINK_TOKEN_TTL)
    return token


def bot_deep_link(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


# --- Update routing ---


def handle_update(update: dict) -> str:
    """Bitta update'ni qayta ishlaydi; qisqa amal-nomi qaytaradi (log/test uchun)."""
    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return "ignored"

    command, _, args = text.partition(" ")
    args = args.strip()
    if command == "/start":
        return _cmd_start(chat_id, args)
    if command == "/stop":
        return _cmd_stop(chat_id)
    if command == "/search":
        return _cmd_search(chat_id, args)
    send_message(chat_id, HELP_TEXT)
    return "help"


def _cmd_start(chat_id: int, token: str) -> str:
    from users.models import Profile

    if token:
        user_id = cache.get(_LINK_PREFIX + token)
        if user_id is None:
            send_message(
                chat_id,
                "Havola eskirgan yoki allaqachon ishlatilgan. Saytdagi Sozlamalar "
                "bo'limidan yangi havola oling.",
            )
            return "link_expired"
        cache.delete(_LINK_PREFIX + token)  # bir martalik [AC-1]

        if Profile.objects.filter(telegram_chat_id=chat_id).exclude(user_id=user_id).exists():
            send_message(
                chat_id,
                "Bu Telegram boshqa hisobga ulangan. Avval o'sha hisob "
                "Sozlamalaridan uzing, keyin qayta urinib ko'ring.",
            )
            return "link_conflict"

        updated = Profile.objects.filter(user_id=user_id).update(
            telegram_chat_id=chat_id, notify_new_episode_telegram=True
        )
        if not updated:
            return "link_no_profile"
        send_message(
            chat_id,
            "✅ Hisobingiz ulandi! Kuzatayotgan seriallaringizning yangi qismlari "
            "haqida endi shu yerda xabar olasiz.\n\n" + HELP_TEXT,
        )
        return "linked"

    # Tokensiz /start
    linked = Profile.objects.filter(telegram_chat_id=chat_id)
    if linked.exists():
        linked.update(notify_new_episode_telegram=True)
        send_message(chat_id, "Xabarlar yoqildi. " + HELP_TEXT)
        return "already_linked"
    send_message(
        chat_id,
        "Salom! Hisobni ulash uchun saytdagi Sozlamalar sahifasida "
        f"«Botga ulash» tugmasini bosing: {settings.SITE_URL}/users/settings/",
    )
    return "start_unlinked"


def _cmd_stop(chat_id: int) -> str:
    from users.models import Profile

    updated = Profile.objects.filter(telegram_chat_id=chat_id).update(
        notify_new_episode_telegram=False
    )
    if updated:
        send_message(chat_id, "Yangi-qism xabarlari o'chirildi. Qayta yoqish: /start")
        return "stopped"
    send_message(chat_id, "Hisob ulanmagan. " + HELP_TEXT)
    return "stop_unlinked"


def _cmd_search(chat_id: int, query: str) -> str:
    from drama.models import Movie
    from drama.services.search import search_movies

    if len(query) < 2:
        send_message(chat_id, "Qidiruv uchun kamida 2 belgi yozing: /search Vinchenzo")
        return "search_short"
    results = list(search_movies(Movie.objects.published(), query)[:5])
    if not results:
        send_message(chat_id, f"«{query}» bo'yicha hech narsa topilmadi.")
        return "search_empty"
    lines = [f"• {m.title}\n  {settings.SITE_URL}{m.get_absolute_url()}" for m in results]
    send_message(chat_id, "Topilganlar:\n\n" + "\n".join(lines))
    return "search_ok"


# --- Webhook view ---


@csrf_exempt
@require_POST
def telegram_webhook(request: HttpRequest) -> JsonResponse:
    """POST /webhooks/telegram/ — Telegram update'lari [AC-4].

    Secret sozlanmagan bo'lsa ham 403 — himoyasiz webhook ochiq qolmaydi.
    """
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # bytes solishtirish: compare_digest non-ASCII str'da TypeError otadi (500 emas, 403)
    if not secret or not hmac.compare_digest(provided.encode(), secret.encode()):
        return JsonResponse({"detail": "forbidden"}, status=403)

    try:
        update = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "invalid json"}, status=400)

    try:
        action = handle_update(update)
    except TelegramBlocked:
        action = "blocked"  # javob yozayotganda user bloklagan — jim o'tamiz
    except Exception:
        logger.exception("telegram_webhook: update qayta ishlashda xato")
        action = "error"  # 200 — Telegram shu update'ni qayta urmasin
    return JsonResponse({"ok": True, "action": action})
