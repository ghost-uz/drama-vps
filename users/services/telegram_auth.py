"""users/services/telegram_auth.py — Telegram login (Login Widget + Mini App) [P6-T2].

Tasdiqlash sof stdlib HMAC bilan (allauth telegram provideri EMAS — to'liq nazorat
+ Mini App initData). Ikki oqim, ikki xil sir:

  * Login Widget (brauzer):  secret = sha256(bot_token);             HMAC(secret, data)
  * Mini App initData:       secret = HMAC(b"WebAppData", bot_token);  HMAC(secret, data)

Tasdiqlangan Telegram ID allauth SocialAccount(provider="telegram", uid=<id>)
jadvaliga yoziladi — AVTORITAR (unique, foydalanuvchi tahrirlay olmaydi). Erkin
`Profile.telegram_id` maydoni faqat ko'rsatish/bildirishnoma uchun mirror qilinadi.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils.text import slugify

TELEGRAM_PROVIDER = "telegram"


def _valid_hash(data_check_string: str, provided_hash: str, secret_key: bytes) -> bool:
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, provided_hash or "")


def _fresh(auth_date: object, max_age: int) -> bool:
    """auth_date (unix sekund) max_age ichidami. HMAC token'siz soxtalashtirib
    bo'lmaydi → faqat eski (replay) payload'ni rad etamiz, kelajakni emas."""
    try:
        ts = int(auth_date)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return (time.time() - ts) <= max_age


def _normalize(fields: dict) -> dict:
    return {
        "id": str(fields.get("id") or ""),
        "username": (fields.get("username") or "").strip(),
        "first_name": (fields.get("first_name") or "").strip(),
        "last_name": (fields.get("last_name") or "").strip(),
        "photo_url": (fields.get("photo_url") or "").strip(),
    }


def verify_login_widget(params: dict, *, bot_token: str, max_age: int) -> dict | None:
    """Login Widget qaytgan query params'ni tekshiradi; yaroqsiz/eskirgan → None."""
    if not bot_token:
        return None
    provided_hash = params.get("hash", "")
    if not provided_hash or not _fresh(params.get("auth_date"), max_age):
        return None
    data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in params.items() if k != "hash"))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    if not _valid_hash(data_check_string, provided_hash, secret_key):
        return None
    data = _normalize(params)
    return data if data["id"] else None


def verify_webapp_init_data(init_data: str, *, bot_token: str, max_age: int) -> dict | None:
    """Mini App `initData` (query-string) ni tekshiradi; yaroqsiz → None.

    Widget'dan farqi: secret = HMAC-SHA256(key=b"WebAppData", msg=bot_token);
    `user` maydoni JSON string (id/username shu yerda).
    """
    if not bot_token or not init_data:
        return None
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = fields.get("hash", "")
    if not provided_hash or not _fresh(fields.get("auth_date"), max_age):
        return None
    data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in fields.items() if k != "hash"))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    if not _valid_hash(data_check_string, provided_hash, secret_key):
        return None
    try:
        user_obj = json.loads(fields.get("user", "{}"))
    except (ValueError, TypeError):
        user_obj = {}
    data = _normalize(user_obj)
    return data if data["id"] else None


def _unique_username(base: str) -> str:
    """Bo'sh bo'lmagan, band bo'lmagan username (≥4 belgi — ACCOUNT_USERNAME_MIN_LENGTH)."""
    cleaned = slugify(base).replace("-", "_")
    if len(cleaned) < 4:
        cleaned = f"tg_{cleaned}".rstrip("_") if cleaned else "tg_user"
    candidate, i = cleaned, 0
    while User.objects.filter(username__iexact=candidate).exists():
        i += 1
        candidate = f"{cleaned}{i}"
    return candidate


def _mirror_to_profile(user: User, tg: dict) -> None:
    """Profile.telegram_id ni ko'rsatish uchun to'ldiradi (auth kaliti EMAS)."""
    profile = getattr(user, "profile", None)
    if profile is not None and profile.telegram_id != tg["id"]:
        profile.telegram_id = tg["id"][:30]
        profile.save(update_fields=["telegram_id"])


@transaction.atomic
def get_or_create_user(tg: dict, *, current_user: User | None = None) -> tuple[User, bool]:
    """Tasdiqlangan Telegram ma'lumotidan user topadi/bog'laydi/yaratadi → (user, created).

    * SocialAccount(telegram, uid) mavjud → o'sha user (mavjudga kirish).
    * current_user autentifikatsiyalangan → shu hisobga bog'lash.
    * aks holda → yangi emailsiz, parolsiz user (username tg username'dan).
    """
    uid = tg["id"]
    account = (
        SocialAccount.objects.select_related("user")
        .filter(provider=TELEGRAM_PROVIDER, uid=uid)
        .first()
    )
    if account is not None:
        _mirror_to_profile(account.user, tg)
        return account.user, False

    if current_user is not None and current_user.is_authenticated:
        user, created = current_user, False
    else:
        user = User(username=_unique_username(tg["username"] or f"tg_{uid}"))
        user.first_name = tg["first_name"][:150]
        user.set_unusable_password()
        user.save()
        created = True

    try:
        SocialAccount.objects.create(user=user, provider=TELEGRAM_PROVIDER, uid=uid, extra_data=tg)
    except IntegrityError:
        # Poyga: bu uid oraliqda yaratilgan → mavjudini qaytar.
        account = SocialAccount.objects.select_related("user").get(
            provider=TELEGRAM_PROVIDER, uid=uid
        )
        return account.user, False
    _mirror_to_profile(user, tg)
    return user, created
