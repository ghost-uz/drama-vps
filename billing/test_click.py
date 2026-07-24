"""billing Click testlari [V2F-T1] — Prepare/Complete callback oqimi.

Sandbox = Click merchant callback'larini simulyatsiya (real tarmoqsiz):
Prepare -> Complete -> (Cancel). Invariantlar: imzo tekshiruvi, idempotentlik
(double-complete bir marta kredit), ledger orqali Coin, summa/holat gvardlari.
"""

from __future__ import annotations

import hashlib

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from billing import services
from billing.models import Order
from billing.providers import click
from users.models import CoinTransaction

SECRET = "click-secret-key"
SERVICE_ID = "12345"


@pytest.fixture
def click_settings(settings):
    settings.CLICK_SECRET_KEY = SECRET
    settings.CLICK_SERVICE_ID = SERVICE_ID
    settings.CLICK_MERCHANT_ID = "merch-1"
    settings.CLICK_CHECKOUT_URL = "https://my.click.uz/services/pay"
    return settings


def _user(username="clicker", balance=0):
    user = User.objects.create_user(username=username, password="pass12345")
    if balance:
        user.profile.balance = balance
        user.profile.save(update_fields=["balance"])
    return user


def _order(user=None, amount_uzs=10000):
    return services.create_order(user or _user(), Order.Provider.CLICK, amount_uzs)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()  # noqa: S324


def _prepare_params(
    order, *, click_trans_id="click-1", amount=None, sign_time="2026-07-24 10:00:00"
):
    amount = str(order.amount_uzs) if amount is None else str(amount)
    params = {
        "click_trans_id": click_trans_id,
        "service_id": SERVICE_ID,
        "click_paydoc_id": "pd-1",
        "merchant_trans_id": str(order.id),
        "amount": amount,
        "action": "0",
        "sign_time": sign_time,
    }
    sign = _md5(f"{click_trans_id}{SERVICE_ID}{SECRET}{order.id}{amount}0{sign_time}")
    params["sign_string"] = sign
    return params


def _complete_params(
    order, *, click_trans_id="click-1", amount=None, error="0", sign_time="2026-07-24 10:05:00"
):
    amount = str(order.amount_uzs) if amount is None else str(amount)
    prepare_id = click._prepare_id(order)
    params = {
        "click_trans_id": click_trans_id,
        "service_id": SERVICE_ID,
        "click_paydoc_id": "pd-1",
        "merchant_trans_id": str(order.id),
        "merchant_prepare_id": str(prepare_id),
        "amount": amount,
        "action": "1",
        "error": error,
        "sign_time": sign_time,
    }
    sign = _md5(f"{click_trans_id}{SERVICE_ID}{SECRET}{order.id}{prepare_id}{amount}1{sign_time}")
    params["sign_string"] = sign
    return params


def _post(client, name, params):
    return client.post(reverse(name), data=params)  # form-encoded


# ---------------------------------------------------------------------------
# Imzo
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_prepare_bad_sign_rejected(client, click_settings):
    order = _order()
    params = _prepare_params(order)
    params["sign_string"] = "deadbeef"
    resp = _post(client, "billing:click_prepare", params)
    assert resp.json()["error"] == click.ERR_SIGN_CHECK


@pytest.mark.django_db
def test_prepare_missing_key_rejects_all(client, settings):
    """CLICK_SECRET_KEY sozlanmagan (dev) -> hamma imzo rad (xavfsiz default)."""
    settings.CLICK_SECRET_KEY = ""
    settings.CLICK_SERVICE_ID = SERVICE_ID
    order = _order()
    resp = _post(client, "billing:click_prepare", _prepare_params(order))
    assert resp.json()["error"] == click.ERR_SIGN_CHECK


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_prepare_valid(client, click_settings):
    order = _order()
    resp = _post(client, "billing:click_prepare", _prepare_params(order))
    body = resp.json()
    assert body["error"] == click.ERR_SUCCESS
    assert body["merchant_prepare_id"] == click._prepare_id(order)
    order.refresh_from_db()
    assert order.provider_txn_id == "click-1"
    assert order.provider_state == click.STATE_PREPARED
    assert order.status == Order.Status.CREATED  # hali kreditlanmagan


@pytest.mark.django_db
def test_prepare_wrong_amount(client, click_settings):
    order = _order(amount_uzs=10000)
    resp = _post(client, "billing:click_prepare", _prepare_params(order, amount=9999))
    assert resp.json()["error"] == click.ERR_INVALID_AMOUNT


@pytest.mark.django_db
def test_prepare_order_not_found(client, click_settings):
    order = _order()
    params = _prepare_params(order)
    # merchant_trans_id'ni mavjud bo'lmagan UUID'ga o'zgartiramiz (+ imzo mos)
    import uuid

    fake = str(uuid.uuid4())
    params["merchant_trans_id"] = fake
    params["sign_string"] = _md5(
        f"click-1{SERVICE_ID}{SECRET}{fake}{order.amount_uzs}02026-07-24 10:00:00"
    )
    resp = _post(client, "billing:click_prepare", params)
    assert resp.json()["error"] == click.ERR_ORDER_NOT_FOUND


@pytest.mark.django_db
def test_prepare_idempotent(client, click_settings):
    order = _order()
    b1 = _post(client, "billing:click_prepare", _prepare_params(order)).json()
    b2 = _post(client, "billing:click_prepare", _prepare_params(order)).json()
    assert b1["error"] == b2["error"] == click.ERR_SUCCESS
    assert b1["merchant_prepare_id"] == b2["merchant_prepare_id"]


# ---------------------------------------------------------------------------
# Complete — kredit ledger orqali + idempotent
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_complete_credits_via_ledger(client, click_settings):
    user = _user()
    order = _order(user=user, amount_uzs=10000)  # 10 Coin
    _post(client, "billing:click_prepare", _prepare_params(order))
    resp = _post(client, "billing:click_complete", _complete_params(order))
    body = resp.json()
    assert body["error"] == click.ERR_SUCCESS

    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    user.profile.refresh_from_db()
    assert user.profile.balance == 10
    # Ledger yozuvi CLICK turida
    tx = CoinTransaction.objects.get(profile=user.profile)
    assert tx.type == CoinTransaction.Type.CLICK
    assert tx.amount == 10


@pytest.mark.django_db
def test_complete_idempotent_no_double_credit(client, click_settings):
    user = _user()
    order = _order(user=user, amount_uzs=10000)
    _post(client, "billing:click_prepare", _prepare_params(order))
    r1 = _post(client, "billing:click_complete", _complete_params(order)).json()
    r2 = _post(client, "billing:click_complete", _complete_params(order)).json()
    assert r1["error"] == r2["error"] == click.ERR_SUCCESS
    user.profile.refresh_from_db()
    assert user.profile.balance == 10  # ikki marta EMAS
    assert CoinTransaction.objects.filter(profile=user.profile).count() == 1


@pytest.mark.django_db
def test_complete_bad_sign_rejected(client, click_settings):
    order = _order()
    _post(client, "billing:click_prepare", _prepare_params(order))
    params = _complete_params(order)
    params["sign_string"] = "bad"
    resp = _post(client, "billing:click_complete", params)
    assert resp.json()["error"] == click.ERR_SIGN_CHECK
    order.refresh_from_db()
    assert order.status == Order.Status.CREATED  # kreditlanmagan


@pytest.mark.django_db
def test_complete_prepare_id_mismatch(client, click_settings):
    order = _order()
    _post(client, "billing:click_prepare", _prepare_params(order))
    params = _complete_params(order)
    # merchant_prepare_id'ni buzamiz (imzoni ham mos qilib, lekin ID boshqa)
    wrong = "999999"
    params["merchant_prepare_id"] = wrong
    params["sign_string"] = _md5(
        f"click-1{SERVICE_ID}{SECRET}{order.id}{wrong}{order.amount_uzs}12026-07-24 10:05:00"
    )
    resp = _post(client, "billing:click_complete", params)
    assert resp.json()["error"] == click.ERR_TXN_NOT_FOUND


@pytest.mark.django_db
def test_complete_without_prepare(client, click_settings):
    """Prepare bo'lmasa complete -> tranzaksiya topilmadi."""
    order = _order()
    resp = _post(client, "billing:click_complete", _complete_params(order))
    assert resp.json()["error"] == click.ERR_TXN_NOT_FOUND


@pytest.mark.django_db
def test_complete_click_error_cancels(client, click_settings):
    """Click error<0 yuborsa (foydalanuvchi bekor qildi) -> buyurtma bekor."""
    order = _order()
    _post(client, "billing:click_prepare", _prepare_params(order))
    resp = _post(client, "billing:click_complete", _complete_params(order, error="-1"))
    assert resp.json()["error"] == click.ERR_CANCELLED
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELED


@pytest.mark.django_db
def test_complete_refund_after_paid_then_cancel(client, click_settings):
    """To'langandan keyin bekor -> Coin qaytariladi (ledger refund)."""
    user = _user()
    order = _order(user=user, amount_uzs=10000)
    _post(client, "billing:click_prepare", _prepare_params(order))
    _post(client, "billing:click_complete", _complete_params(order))
    user.profile.refresh_from_db()
    assert user.profile.balance == 10

    # Yangi complete: Click error bilan (bekor) — refund
    _post(
        client,
        "billing:click_complete",
        _complete_params(order, error="-9", sign_time="2026-07-24 11:00:00"),
    )
    # Allaqachon PAID edi -> mark_canceled refund qiladi
    user.profile.refresh_from_db()
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELED
    assert user.profile.balance == 0  # 10 kredit - 10 refund
    assert CoinTransaction.objects.filter(
        profile=user.profile, type=CoinTransaction.Type.REFUND
    ).exists()


# ---------------------------------------------------------------------------
# checkout_url
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_checkout_url_built(click_settings):
    order = _order(amount_uzs=5000)
    url = click.checkout_url(order, return_url="https://drama.uz/users/transactions/")
    assert url.startswith("https://my.click.uz/services/pay?")
    assert f"transaction_param={order.id}" in url
    assert "service_id=12345" in url
    assert "amount=5000" in url


@pytest.mark.django_db
def test_checkout_url_empty_when_unconfigured(settings):
    settings.CLICK_SERVICE_ID = ""
    settings.CLICK_MERCHANT_ID = ""
    order = _order()
    assert click.checkout_url(order) == ""


@pytest.mark.django_db
def test_checkout_view_creates_click_order(client, click_settings):
    user = _user()
    client.force_login(user)
    resp = client.post(reverse("billing:checkout"), {"amount_uzs": "5000", "provider": "click"})
    assert resp.status_code == 302
    assert "my.click.uz" in resp["Location"]
    order = Order.objects.get(user=user)
    assert order.provider == Order.Provider.CLICK
    assert order.coins == 5
