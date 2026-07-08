"""users/test_social_auth.py — ijtimoiy login (Google + Telegram) [P6-T2].

Telegram HMAC ikki oqimi (Login Widget + Mini App), hisob yaratish/bog'lash,
view'lar, throttle, hamda Google allauth wiring smoke testlari.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from users.services import telegram_auth

BOT_TOKEN = "123456:TEST_TOKEN"


def _widget_params(bot_token=BOT_TOKEN, **over):
    """Yaroqli Login Widget query params (imzo bilan) quradi."""
    params = {
        "id": "777000",
        "first_name": "Aziz",
        "username": "aziz_tg",
        "auth_date": str(int(time.time())),
    }
    params.update(over)
    dcs = "\n".join(sorted(f"{k}={v}" for k, v in params.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    params["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return params


def _webapp_init_data(bot_token=BOT_TOKEN, user=None, **over):
    """Yaroqli Mini App initData (query-string, imzo bilan) quradi."""
    user = user or {"id": 777000, "first_name": "Aziz", "username": "aziz_tg"}
    fields = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAErandom",
    }
    fields.update(over)
    dcs = "\n".join(sorted(f"{k}={v}" for k, v in fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


# ---- Telegram imzo tekshiruvi (sof funksiya, DB kerak emas) --------------------


def test_widget_valid_signature_returns_data():
    data = telegram_auth.verify_login_widget(_widget_params(), bot_token=BOT_TOKEN, max_age=86400)
    assert data is not None
    assert data["id"] == "777000"
    assert data["username"] == "aziz_tg"


def test_widget_tampered_hash_rejected():
    params = _widget_params()
    params["hash"] = "deadbeef" + params["hash"][8:]
    assert telegram_auth.verify_login_widget(params, bot_token=BOT_TOKEN, max_age=86400) is None


def test_widget_tampered_field_rejected():
    # id o'zgartirilsa imzo mos kelmaydi (boshqa hisobga kirishga urinish).
    params = _widget_params()
    params["id"] = "999999"
    assert telegram_auth.verify_login_widget(params, bot_token=BOT_TOKEN, max_age=86400) is None


def test_widget_expired_auth_date_rejected():
    params = _widget_params(auth_date=str(int(time.time()) - 100000))
    assert telegram_auth.verify_login_widget(params, bot_token=BOT_TOKEN, max_age=86400) is None


def test_widget_no_bot_token_rejected():
    assert telegram_auth.verify_login_widget(_widget_params(), bot_token="", max_age=86400) is None


def test_widget_wrong_bot_token_rejected():
    # Imzo boshqa token bilan → o'zga bot payloadi qabul qilinmaydi.
    params = _widget_params(bot_token="000:OTHER")
    assert telegram_auth.verify_login_widget(params, bot_token=BOT_TOKEN, max_age=86400) is None


def test_webapp_valid_init_data_returns_data():
    init = _webapp_init_data()
    data = telegram_auth.verify_webapp_init_data(init, bot_token=BOT_TOKEN, max_age=86400)
    assert data is not None
    assert data["id"] == "777000"
    assert data["username"] == "aziz_tg"


def test_webapp_tampered_rejected():
    init = _webapp_init_data() + "0"  # hash oxirini buzish
    assert telegram_auth.verify_webapp_init_data(init, bot_token=BOT_TOKEN, max_age=86400) is None


def test_widget_non_integer_auth_date_rejected():
    params = _widget_params(auth_date="not-a-number")
    assert telegram_auth.verify_login_widget(params, bot_token=BOT_TOKEN, max_age=86400) is None


def test_webapp_bad_user_json_rejected():
    # Imzo yaroqli, lekin `user` maydoni buzuq JSON → id ajratilmaydi → None.
    fields = {"user": "not-json{", "auth_date": str(int(time.time())), "query_id": "AA"}
    dcs = "\n".join(sorted(f"{k}={v}" for k, v in fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    init = urlencode(fields)
    assert telegram_auth.verify_webapp_init_data(init, bot_token=BOT_TOKEN, max_age=86400) is None


# ---- Hisob yaratish / bog'lash -------------------------------------------------

TG = {"id": "777000", "username": "aziz_tg", "first_name": "Aziz", "last_name": "", "photo_url": ""}


@pytest.mark.django_db
def test_get_or_create_new_user_binds_socialaccount_and_profile():
    user, created = telegram_auth.get_or_create_user(dict(TG))
    assert created is True
    # Avtoritar binding — SocialAccount (unique, tahrirlanmaydi).
    assert SocialAccount.objects.filter(provider="telegram", uid="777000", user=user).exists()
    # Profile signal ishladi + telegram_id ko'rsatish uchun mirror qilindi.
    assert user.profile.telegram_id == "777000"
    # Emailsiz, parolsiz hisob (Telegram — ishlab bo'lmaydigan parol).
    assert user.email == ""
    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_get_or_create_existing_returns_same_user_no_duplicate():
    user1, _ = telegram_auth.get_or_create_user(dict(TG))
    before = User.objects.count()
    user2, created2 = telegram_auth.get_or_create_user(dict(TG))
    assert user2 == user1
    assert created2 is False
    assert User.objects.count() == before  # yangi user yaratilmadi
    assert SocialAccount.objects.filter(provider="telegram", uid="777000").count() == 1


@pytest.mark.django_db
def test_get_or_create_links_to_authenticated_user():
    existing = User.objects.create_user(username="borhisob", password="parol12345")
    user, created = telegram_auth.get_or_create_user(dict(TG), current_user=existing)
    assert user == existing  # yangi hisob EMAS — mavjudga bog'landi
    assert created is False
    assert SocialAccount.objects.filter(provider="telegram", uid="777000", user=existing).exists()
    assert existing.profile.telegram_id == "777000"


@pytest.mark.django_db
def test_username_collision_is_uniquified():
    User.objects.create_user(username="aziz_tg", password="x12345678")
    user, _ = telegram_auth.get_or_create_user(dict(TG))
    assert user.username != "aziz_tg"  # band → suffikslandi
    assert user.username.startswith("aziz_tg")


# ---- telegram_login view (GET widget + POST Mini App) --------------------------


@override_settings(TELEGRAM_LOGIN_BOT_TOKEN=BOT_TOKEN, TELEGRAM_LOGIN_MAX_AGE=86400)
@pytest.mark.django_db
def test_view_get_widget_logs_in_and_creates(client):
    cache.clear()
    resp = client.get(reverse("users:telegram_login"), _widget_params())
    assert resp.status_code == 302
    assert SocialAccount.objects.filter(provider="telegram", uid="777000").exists()
    assert "_auth_user_id" in client.session  # sessiyaga login qilindi


@override_settings(TELEGRAM_LOGIN_BOT_TOKEN=BOT_TOKEN)
@pytest.mark.django_db
def test_view_get_invalid_redirects_to_login(client):
    cache.clear()
    params = _widget_params()
    params["hash"] = "bad"
    resp = client.get(reverse("users:telegram_login"), params)
    assert resp.status_code == 302
    assert resp.url == reverse("users:login")
    assert "_auth_user_id" not in client.session


@override_settings(TELEGRAM_LOGIN_BOT_TOKEN=BOT_TOKEN)
@pytest.mark.django_db
def test_view_post_webapp_logs_in(client):
    cache.clear()
    resp = client.post(reverse("users:telegram_login"), {"init_data": _webapp_init_data()})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "_auth_user_id" in client.session


@override_settings(TELEGRAM_LOGIN_BOT_TOKEN=BOT_TOKEN)
@pytest.mark.django_db
def test_view_post_webapp_invalid_403(client):
    cache.clear()
    resp = client.post(reverse("users:telegram_login"), {"init_data": "garbage"})
    assert resp.status_code == 403
    assert resp.json()["ok"] is False


@override_settings(TELEGRAM_LOGIN_BOT_TOKEN=BOT_TOKEN)
@pytest.mark.django_db
def test_view_rate_limited_429(client):
    cache.clear()
    url = reverse("users:telegram_login")
    params = _widget_params()
    params["hash"] = "bad"  # yaroqsiz ham bo'ladi — throttle view'dan OLDIN sanaydi
    statuses = {client.get(url, params).status_code for _ in range(32)}
    assert 429 in statuses  # 30/min chegara oshdi


# ---- Login sahifasi tugmalari + CSP + Google allauth wiring --------------------

_GOOGLE_APP = {
    "google": {
        "APP": {"client_id": "test-id", "secret": "s", "key": ""},
        "SCOPE": ["profile", "email"],
    }
}


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="test-id",
    TELEGRAM_LOGIN_BOT_USERNAME="drama_test_bot",
    SOCIALACCOUNT_PROVIDERS=_GOOGLE_APP,
)
@pytest.mark.django_db
def test_login_page_shows_social_buttons_and_csp(client):
    resp = client.get(reverse("users:login"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "telegram-widget.js" in html
    assert 'data-telegram-login="drama_test_bot"' in html
    assert "/accounts/google/login/" in html
    csp = resp["Content-Security-Policy"]
    assert "telegram.org" in csp and "oauth.telegram.org" in csp


@override_settings(GOOGLE_OAUTH_CLIENT_ID="", TELEGRAM_LOGIN_BOT_USERNAME="")
@pytest.mark.django_db
def test_login_page_hides_buttons_when_unconfigured(client):
    html = client.get(reverse("users:login")).content.decode()
    assert "telegram-widget.js" not in html
    assert "Google bilan davom etish" not in html


@override_settings(SOCIALACCOUNT_PROVIDERS=_GOOGLE_APP)
@pytest.mark.django_db
def test_google_login_entrypoint_redirects_to_google(client):
    # allauth wiring end-to-end (Google serveri mock qilinmaydi): SOCIALACCOUNT_LOGIN_ON_GET
    # tufayli GET darhol Google auth URL'iga yo'naltiradi.
    resp = client.get("/accounts/google/login/")
    assert resp.status_code == 302
    assert "accounts.google.com" in resp["Location"]
