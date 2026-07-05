"""users app — P1-T4: Coin hamyon ledgeri (wallet service + CoinTransaction).

Yagona invariant: Profile.balance == SUM(CoinTransaction.amount).
Barcha coin harakatlari (topup, sovg'a, funding, VIP, refund) wallet orqali o'tadi.
"""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.urls import reverse
from PIL import Image

from drama.models import Actor, ActorGift, Movie
from funding.models import FundingProject
from users.models import CoinTransaction, TopUpRequest
from users.services import wallet


def _image(name="x.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def _user(username="u1", balance=0):
    user = User.objects.create_user(username=username, password="pass12345")
    profile = user.profile  # post_save signal profilni yaratadi
    if balance:
        profile.balance = balance
        profile.save(update_fields=["balance"])
    return user


# --- wallet service (sof DB, HTTP'siz) ---


@pytest.mark.django_db
def test_credit_increases_balance_and_records_txn():
    user = _user(balance=10)
    txn = wallet.credit(user.profile, 25, CoinTransaction.Type.TOPUP)
    user.profile.refresh_from_db()
    assert user.profile.balance == 35
    assert txn.amount == 25
    assert txn.balance_after == 35
    assert txn.type == "topup"


@pytest.mark.django_db
def test_debit_decreases_balance_and_records_negative_amount():
    user = _user(balance=50)
    txn = wallet.debit(user.profile, 20, CoinTransaction.Type.GIFT)
    user.profile.refresh_from_db()
    assert user.profile.balance == 30
    assert txn.amount == -20
    assert txn.balance_after == 30


@pytest.mark.django_db
def test_debit_insufficient_raises_and_records_nothing():
    user = _user(balance=5)
    with pytest.raises(wallet.InsufficientFundsError):
        wallet.debit(user.profile, 10, CoinTransaction.Type.GIFT)
    user.profile.refresh_from_db()
    assert user.profile.balance == 5
    assert CoinTransaction.objects.count() == 0


@pytest.mark.django_db
def test_debit_allow_negative_goes_below_zero():
    user = _user(balance=5)
    txn = wallet.debit(user.profile, 10, CoinTransaction.Type.REFUND, allow_negative=True)
    user.profile.refresh_from_db()
    assert user.profile.balance == -5
    assert txn.balance_after == -5


@pytest.mark.django_db
def test_credit_and_debit_reject_nonpositive_amount():
    user = _user(balance=5)
    with pytest.raises(ValueError):
        wallet.credit(user.profile, 0, CoinTransaction.Type.TOPUP)
    with pytest.raises(ValueError):
        wallet.debit(user.profile, -3, CoinTransaction.Type.GIFT)


@pytest.mark.django_db
def test_balance_equals_sum_of_transactions_invariant():
    user = _user(balance=0)
    wallet.credit(user.profile, 100, CoinTransaction.Type.TOPUP)
    wallet.debit(user.profile, 30, CoinTransaction.Type.GIFT)
    wallet.debit(user.profile, 15, CoinTransaction.Type.VIP)
    user.profile.refresh_from_db()
    total = CoinTransaction.objects.filter(profile=user.profile).aggregate(s=Sum("amount"))["s"]
    assert total == user.profile.balance == 55


# --- TopUpRequest model (admin approve/reversal oqimi) ---


@pytest.mark.django_db
def test_topup_approval_credits_via_ledger():
    user = _user(balance=0)
    req = TopUpRequest.objects.create(user=user, amount_uzs=50000, receipt_image=_image("r.jpg"))
    assert req.points == 50  # 50000 // 1000
    req.status = "approved"
    req.save()
    user.profile.refresh_from_db()
    assert user.profile.balance == 50
    txn = CoinTransaction.objects.get(reference=f"topup:{req.pk}", type="topup")
    assert txn.amount == 50


@pytest.mark.django_db
def test_topup_reversal_debits_back():
    user = _user(balance=0)
    req = TopUpRequest.objects.create(user=user, amount_uzs=30000, receipt_image=_image("r.jpg"))
    req.status = "approved"
    req.save()
    req.status = "rejected"
    req.save()
    user.profile.refresh_from_db()
    assert user.profile.balance == 0
    assert CoinTransaction.objects.filter(reference=f"topup:{req.pk}", type="refund").exists()


# --- view oqimlari (gift, funding, VIP) ---


@pytest.mark.django_db
def test_buy_premium_debits_and_grants_via_ledger(client):
    user = _user(balance=20)
    client.force_login(user)
    resp = client.post(reverse("users:buy_premium"))
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.balance == 5
    assert user.profile.is_premium is True
    txn = CoinTransaction.objects.get(profile=user.profile, type="vip")
    assert txn.amount == -15
    assert txn.balance_after == 5


@pytest.mark.django_db
def test_buy_premium_insufficient_keeps_balance_and_no_premium(client):
    user = _user(balance=10)
    client.force_login(user)
    client.post(reverse("users:buy_premium"))
    user.profile.refresh_from_db()
    assert user.profile.balance == 10
    assert user.profile.is_premium is False
    assert not CoinTransaction.objects.filter(type="vip").exists()


@pytest.mark.django_db
def test_gift_view_debits_via_ledger(client):
    user = _user(balance=100)
    client.force_login(user)
    actor = Actor.objects.create(name="Test Actor", image=_image("a.jpg"))
    resp = client.post(reverse("drama:send_gift_to_actor", args=[actor.id]), {"gift": "crown"})
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.balance == 80  # crown = 20
    txn = CoinTransaction.objects.get(profile=user.profile, type="gift")
    assert txn.amount == -20
    actor.refresh_from_db()
    assert actor.total_gifts == 20


@pytest.mark.django_db
def test_gift_view_insufficient_creates_no_gift(client):
    user = _user(balance=5)
    client.force_login(user)
    actor = Actor.objects.create(name="Poor Target", image=_image("b.jpg"))
    client.post(reverse("drama:send_gift_to_actor", args=[actor.id]), {"gift": "crown"})
    user.profile.refresh_from_db()
    assert user.profile.balance == 5
    assert not CoinTransaction.objects.filter(type="gift").exists()
    assert ActorGift.objects.count() == 0


@pytest.mark.django_db
def test_funding_contribution_debits_via_ledger(client):
    user = _user(balance=200)
    client.force_login(user)
    movie = Movie.objects.create(
        title="Fund Movie", description="d", country="KR", poster=_image("p.jpg")
    )
    project = FundingProject.objects.create(movie=movie, target_amount=1000)
    resp = client.post(reverse("funding:process", args=[project.id]), {"amount": "60"})
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.balance == 140
    txn = CoinTransaction.objects.get(profile=user.profile, type="funding")
    assert txn.amount == -60
    project.refresh_from_db()
    assert project.collected_amount == 60
    assert project.contributors.count() == 1


@pytest.mark.django_db
def test_opening_balance_migration_backfills_only_nonzero():
    """0012 data-migr: balance!=0 profilga 'opening' txn, nol balansga yo'q."""
    import importlib

    from django.apps import apps as global_apps

    rich = _user(username="rich", balance=120)  # balansni TO'G'RIDAN qo'yadi (ledger'siz)
    poor = _user(username="poor", balance=0)

    migration = importlib.import_module("users.migrations.0012_opening_balances")
    migration.create_opening_balances(global_apps, None)

    txn = CoinTransaction.objects.get(profile=rich.profile, type="opening")
    assert txn.amount == 120
    assert txn.balance_after == 120
    assert not CoinTransaction.objects.filter(profile=poor.profile).exists()


# --- P10-T2: rate limiting (web) ---


@pytest.mark.django_db
def test_login_rate_limited_429():
    """Login brute-force: limitdan keyin 429 + Retry-After (403 EMAS)."""
    from django.core.cache import cache
    from django.test import Client
    from django.urls import reverse

    cache.clear()
    client = Client()
    url = reverse("users:login")
    for _ in range(10):  # settings.RATELIMIT_RATES["login"] = 10/m
        client.post(url, {"username": "yoq", "password": "notogri"})
    resp = client.post(url, {"username": "yoq", "password": "notogri"})
    assert resp.status_code == 429
    assert resp["Retry-After"] == "60"
    assert "detail" in resp.json()
    cache.clear()


@pytest.mark.django_db
def test_login_get_not_limited():
    """GET (forma ochish) cheklanmaydi — faqat POST urinishlar sanaladi."""
    from django.core.cache import cache
    from django.test import Client
    from django.urls import reverse

    cache.clear()
    client = Client()
    for _ in range(15):
        assert client.get(reverse("users:login")).status_code == 200
    cache.clear()


@pytest.mark.django_db
def test_register_rate_limited_429():
    from django.core.cache import cache
    from django.test import Client
    from django.urls import reverse

    cache.clear()
    client = Client()
    url = reverse("users:register")
    for _ in range(5):  # settings.RATELIMIT_RATES["register"] = 5/h
        client.post(url, {})
    assert client.post(url, {}).status_code == 429
    cache.clear()
