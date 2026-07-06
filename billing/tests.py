"""billing testlari [P7-T2] — Payme Merchant API (JSON-RPC) oqimi.

Sandbox = Payme'ning JSON-RPC chaqiruvlarini simulyatsiya (real tarmoqsiz):
Check -> Create -> Perform -> (Cancel). Asosiy invariantlar: idempotentlik
(double-perform bir marta kredit), autentifikatsiya, ledger orqali Coin.
"""

import base64
import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from billing import services
from billing.models import Order
from billing.providers import payme
from users.models import CoinTransaction

PAYME_KEY = "test-merchant-key"


@pytest.fixture
def payme_settings(settings):
    settings.PAYME_KEY = PAYME_KEY
    settings.PAYME_MERCHANT_ID = "test-merchant-id"
    settings.PAYME_CHECKOUT_URL = "https://checkout.test.paycom.uz"
    return settings


def _user(username="payer", balance=0):
    user = User.objects.create_user(username=username, password="pass12345")
    if balance:
        user.profile.balance = balance
        user.profile.save(update_fields=["balance"])
    return user


def _order(user=None, amount_uzs=10000):
    return services.create_order(user or _user(), Order.Provider.PAYME, amount_uzs)


def _rpc(client, method, params, key=PAYME_KEY):
    """Webhook'ga JSON-RPC POST (Basic auth bilan)."""
    creds = base64.b64encode(f"Paycom:{key}".encode()).decode()
    return client.post(
        reverse("billing:payme_webhook"),
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Basic {creds}",
    )


# --- services: narx va buyurtma ---


def test_coins_for_amount():
    assert services.coins_for_amount(10000) == 10
    assert services.coins_for_amount(1500) == 1  # butun bo'linma


@pytest.mark.django_db
def test_create_order_sets_coins():
    order = _order(amount_uzs=25000)
    assert order.coins == 25
    assert order.status == Order.Status.CREATED
    assert order.amount_tiyin == 2500000


# --- webhook: autentifikatsiya ---


@pytest.mark.django_db
def test_webhook_rejects_wrong_key(client, payme_settings):
    """Noto'g'ri merchant kaliti -> -32504 (ruxsatsiz)."""
    resp = _rpc(client, "CheckPerformTransaction", {}, key="wrong")
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32504


@pytest.mark.django_db
def test_webhook_rejects_missing_auth(client, payme_settings):
    resp = client.post(
        reverse("billing:payme_webhook"),
        data=json.dumps({"method": "CheckPerformTransaction", "params": {}}),
        content_type="application/json",
    )
    assert resp.json()["error"]["code"] == -32504


# --- CheckPerformTransaction ---


@pytest.mark.django_db
def test_check_perform_valid_order(client, payme_settings):
    order = _order()
    resp = _rpc(
        client,
        "CheckPerformTransaction",
        {"account": {"order_id": str(order.id)}, "amount": order.amount_tiyin},
    )
    assert resp.json()["result"] == {"allow": True}


@pytest.mark.django_db
def test_check_perform_wrong_amount(client, payme_settings):
    order = _order()
    resp = _rpc(
        client,
        "CheckPerformTransaction",
        {"account": {"order_id": str(order.id)}, "amount": 999},
    )
    assert resp.json()["error"]["code"] == -31001


@pytest.mark.django_db
def test_check_perform_missing_order(client, payme_settings):
    import uuid

    resp = _rpc(
        client,
        "CheckPerformTransaction",
        {"account": {"order_id": str(uuid.uuid4())}, "amount": 1000000},
    )
    err = resp.json()["error"]
    assert err["code"] == -31050
    assert err["data"] == "order_id"


@pytest.mark.django_db
def test_check_perform_malformed_order_id(client, payme_settings):
    """Yaroqsiz UUID (ValidationError) -> -31050, 500 EMAS."""
    resp = _rpc(
        client,
        "CheckPerformTransaction",
        {"account": {"order_id": "not-a-uuid"}, "amount": 1000000},
    )
    assert resp.json()["error"]["code"] == -31050


# --- Create / Perform / Cancel to'liq oqim ---


def _create(client, order):
    return _rpc(
        client,
        "CreateTransaction",
        {
            "id": "payme-txn-1",
            "time": 1000,
            "account": {"order_id": str(order.id)},
            "amount": order.amount_tiyin,
        },
    )


@pytest.mark.django_db
def test_create_transaction(client, payme_settings):
    order = _order()
    result = _create(client, order).json()["result"]
    assert result["state"] == 1
    assert result["transaction"] == str(order.id)
    assert result["create_time"] > 0
    order.refresh_from_db()
    assert order.provider_txn_id == "payme-txn-1"
    assert order.provider_state == 1


@pytest.mark.django_db
def test_create_transaction_idempotent(client, payme_settings):
    """Bir xil id bilan takror CreateTransaction -> AYNAN bir xil natija."""
    order = _order()
    r1 = _create(client, order).json()["result"]
    r2 = _create(client, order).json()["result"]
    assert r1 == r2
    assert Order.objects.get(pk=order.id).provider_txn_id == "payme-txn-1"


@pytest.mark.django_db
def test_perform_transaction_credits_via_ledger(client, payme_settings):
    """Acceptance: PerformTransaction -> Coin ledger orqali avtomatik qo'shiladi."""
    user = _user(balance=0)
    order = _order(user=user, amount_uzs=10000)
    _create(client, order)
    result = _rpc(client, "PerformTransaction", {"id": "payme-txn-1"}).json()["result"]

    assert result["state"] == 2
    assert result["perform_time"] > 0
    user.profile.refresh_from_db()
    assert user.profile.balance == 10  # 10000 UZS / 1000
    txn = CoinTransaction.objects.get(profile=user.profile, type="payme")
    assert txn.amount == 10
    assert txn.reference == f"order:{order.id}"
    order.refresh_from_db()
    assert order.status == Order.Status.PAID


@pytest.mark.django_db
def test_perform_transaction_idempotent_no_double_credit(client, payme_settings):
    """Acceptance (idempotent): takror PerformTransaction ikkinchi marta kredit BERMAYDI."""
    user = _user(balance=0)
    order = _order(user=user, amount_uzs=10000)
    _create(client, order)
    r1 = _rpc(client, "PerformTransaction", {"id": "payme-txn-1"}).json()["result"]
    r2 = _rpc(client, "PerformTransaction", {"id": "payme-txn-1"}).json()["result"]

    assert r1 == r2  # bir xil perform_time — idempotent
    user.profile.refresh_from_db()
    assert user.profile.balance == 10  # 20 EMAS
    assert CoinTransaction.objects.filter(profile=user.profile, type="payme").count() == 1


@pytest.mark.django_db
def test_perform_unknown_transaction(client, payme_settings):
    resp = _rpc(client, "PerformTransaction", {"id": "yoq"})
    assert resp.json()["error"]["code"] == -31003


@pytest.mark.django_db
def test_cancel_before_perform_no_refund(client, payme_settings):
    """Yaratilgan (to'lanmagan) tranzaksiya bekori: state -1, Coin qaytmaydi."""
    user = _user(balance=0)
    order = _order(user=user)
    _create(client, order)
    result = _rpc(client, "CancelTransaction", {"id": "payme-txn-1", "reason": 3}).json()["result"]

    assert result["state"] == -1
    user.profile.refresh_from_db()
    assert user.profile.balance == 0
    assert not CoinTransaction.objects.filter(profile=user.profile).exists()
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELED


@pytest.mark.django_db
def test_cancel_after_perform_refunds_via_ledger(client, payme_settings):
    """To'langan tranzaksiya bekori: state -2, Coin ledger orqali QAYTARILADI."""
    user = _user(balance=0)
    order = _order(user=user, amount_uzs=10000)
    _create(client, order)
    _rpc(client, "PerformTransaction", {"id": "payme-txn-1"})
    result = _rpc(client, "CancelTransaction", {"id": "payme-txn-1", "reason": 5}).json()["result"]

    assert result["state"] == -2
    user.profile.refresh_from_db()
    assert user.profile.balance == 0  # +10 kredit, -10 refund
    assert CoinTransaction.objects.filter(profile=user.profile, type="refund").count() == 1


@pytest.mark.django_db
def test_cancel_idempotent(client, payme_settings):
    """Takror CancelTransaction -> bir xil holat, ikkinchi refund YO'Q."""
    user = _user(balance=0)
    order = _order(user=user, amount_uzs=10000)
    _create(client, order)
    _rpc(client, "PerformTransaction", {"id": "payme-txn-1"})
    _rpc(client, "CancelTransaction", {"id": "payme-txn-1", "reason": 5})
    _rpc(client, "CancelTransaction", {"id": "payme-txn-1", "reason": 5})
    user.profile.refresh_from_db()
    assert user.profile.balance == 0
    assert CoinTransaction.objects.filter(profile=user.profile, type="refund").count() == 1


@pytest.mark.django_db
def test_check_transaction_reports_state(client, payme_settings):
    order = _order()
    _create(client, order)
    _rpc(client, "PerformTransaction", {"id": "payme-txn-1"})
    result = _rpc(client, "CheckTransaction", {"id": "payme-txn-1"}).json()["result"]
    assert result["state"] == 2
    assert result["perform_time"] > 0
    assert result["cancel_time"] == 0


@pytest.mark.django_db
def test_unknown_method(client, payme_settings):
    assert _rpc(client, "FooBar", {}).json()["error"]["code"] == -32601


# --- checkout view + URL ---


@pytest.mark.django_db
def test_checkout_creates_order_and_redirects_to_payme(client, payme_settings):
    """Acceptance: checkout Order yaratadi va Payme sahifasiga redirect."""
    from django.core.cache import cache

    cache.clear()
    user = _user()
    client.force_login(user)
    resp = client.post(reverse("billing:checkout"), {"amount_uzs": "20000"})
    assert resp.status_code == 302
    assert "checkout.test.paycom.uz" in resp.url
    order = Order.objects.get(user=user)
    assert order.coins == 20 and order.status == Order.Status.CREATED
    cache.clear()


@pytest.mark.django_db
def test_checkout_rejects_below_minimum(client, payme_settings):
    from django.core.cache import cache

    cache.clear()
    user = _user()
    client.force_login(user)
    resp = client.post(reverse("billing:checkout"), {"amount_uzs": "500"})
    assert resp.status_code == 302  # xato xabari bilan qayta checkout'ga
    assert not Order.objects.filter(user=user).exists()
    cache.clear()


@pytest.mark.django_db
def test_checkout_warns_when_provider_unconfigured(client, settings):
    """Merchant ID yo'q (dev) -> buyurtma qoladi, qo'lda topup'ga yo'naltiriladi."""
    from django.core.cache import cache

    cache.clear()
    settings.PAYME_MERCHANT_ID = ""
    user = _user()
    client.force_login(user)
    resp = client.post(reverse("billing:checkout"), {"amount_uzs": "10000"})
    assert resp.status_code == 302
    assert reverse("users:topup") in resp.url
    cache.clear()


def test_checkout_url_builds_base64(payme_settings):
    """checkout_url merchant+order+summani base64 bilan kodlaydi."""
    import uuid

    order = Order(id=uuid.uuid4(), amount_uzs=10000, coins=10, provider=Order.Provider.PAYME)
    url = payme.checkout_url(order)
    assert url.startswith("https://checkout.test.paycom.uz/")
    encoded = url.rsplit("/", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    assert f"ac.order_id={order.id}" in decoded
    assert "a=1000000" in decoded  # 10000 UZS = 1000000 tiyin
