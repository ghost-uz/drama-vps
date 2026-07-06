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


# --- P11-T2: double-credit himoya, premium muddati, funding atomiklik ---


@pytest.mark.django_db
def test_topup_double_approve_credits_once():
    """Acceptance (double-credit): approved holida qayta save KREDIT BERMAYDI.

    Guard: old.status=='pending' AND new=='approved' — crypto topup'da ham
    aynan shu pattern (users/models.py CryptoTopUpRequest.save).
    """
    user = _user(balance=0)
    req = TopUpRequest.objects.create(user=user, amount_uzs=5000, receipt_image=_image("r.jpg"))
    req.status = "approved"
    req.save()
    user.profile.refresh_from_db()
    assert user.profile.balance == 5

    req.save()  # approved -> approved (admin qayta saqladi)
    req.status = "approved"
    req.save()
    user.profile.refresh_from_db()
    assert user.profile.balance == 5  # o'zgarmadi
    assert CoinTransaction.objects.filter(profile=user.profile, type="topup").count() == 1


@pytest.mark.django_db
def test_is_currently_premium_expired_is_false():
    """premium_until o'tgan bo'lsa is_premium=True bo'lsa ham premium EMAS."""
    from datetime import timedelta

    from django.utils import timezone

    user = _user()
    profile = user.profile
    profile.is_premium = True
    profile.premium_until = timezone.now() - timedelta(days=1)
    profile.save()
    assert profile.is_currently_premium is False


@pytest.mark.django_db
def test_is_currently_premium_none_until_stays_true():
    """premium_until=None + is_premium=True -> muddatsiz premium (hujjatlangan)."""
    user = _user()
    profile = user.profile
    profile.is_premium = True
    profile.premium_until = None
    profile.save()
    assert profile.is_currently_premium is True


@pytest.mark.django_db
def test_funding_insufficient_is_atomic(client):
    """Coin yetmasa HECH NARSA o'zgarmaydi: contributor/collected/balans/ledger."""
    user = _user(balance=10)
    client.force_login(user)
    movie = Movie.objects.create(
        title="Fund Atom", description="d", country="KR", poster=_image("p.jpg")
    )
    project = FundingProject.objects.create(movie=movie, target_amount=1000)
    resp = client.post(reverse("funding:process", args=[project.id]), {"amount": "60"})
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    project.refresh_from_db()
    assert user.profile.balance == 10
    assert project.collected_amount == 0
    assert project.contributors.count() == 0
    assert not CoinTransaction.objects.filter(profile=user.profile, type="funding").exists()


@pytest.mark.django_db
def test_funding_below_minimum_rejected(client):
    """min_fund_amount (default 50) dan kichik hissa rad — hech narsa yozilmaydi."""
    user = _user(balance=200)
    client.force_login(user)
    movie = Movie.objects.create(
        title="Fund Min", description="d", country="KR", poster=_image("p.jpg")
    )
    project = FundingProject.objects.create(movie=movie, target_amount=1000)
    client.post(reverse("funding:process", args=[project.id]), {"amount": "10"})
    user.profile.refresh_from_db()
    project.refresh_from_db()
    assert user.profile.balance == 200
    assert project.contributors.count() == 0


@pytest.mark.django_db
def test_funding_contribution_grants_access(client):
    """Hissa qo'shgan foydalanuvchi darhol has_access oladi (gating kaliti)."""
    user = _user(balance=200)
    client.force_login(user)
    movie = Movie.objects.create(
        title="Fund Access", description="d", country="KR", poster=_image("p.jpg")
    )
    project = FundingProject.objects.create(movie=movie, target_amount=1000)
    client.post(reverse("funding:process", args=[project.id]), {"amount": "60"})
    assert project.has_access(user.profile) is True


# --- P10-T3: fayl yuklash validatsiyasi (forma-darajali integratsiya) ---


def test_topup_form_rejects_fake_image():
    """HTML fayl .jpg niqobida — forma rad etadi, xato maydonga bog'lanadi."""
    from users.forms import TopUpRequestForm

    fake = SimpleUploadedFile("chek.jpg", b"<html>xss</html>", content_type="image/jpeg")
    form = TopUpRequestForm({"amount_uzs": 10000}, {"receipt_image": fake})
    assert not form.is_valid()
    assert "receipt_image" in form.errors


def test_topup_form_accepts_real_jpeg():
    from users.forms import TopUpRequestForm

    form = TopUpRequestForm({"amount_uzs": 10000}, {"receipt_image": _image("chek.jpg")})
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_topup_receipt_stored_under_random_name(client):
    """Chek asl nomini yo'qotadi: receipts/YYYY/MM/<uuid>.jpg (maxfiylik)."""
    import re

    user = _user()
    client.force_login(user)
    client.post(
        reverse("users:topup"),
        {"amount_uzs": 5000, "receipt_image": _image("passport skan.jpg")},
    )
    topup = TopUpRequest.objects.get(user=user)
    assert re.fullmatch(r"receipts/\d{4}/\d{2}/[0-9a-f]{32}\.jpg", topup.receipt_image.name)
    assert "passport" not in topup.receipt_image.name


# --- P6-T1: email tasdiqlash + parol siyosati + parol tiklash ---

_STRONG = "Kuchli-Parol-42"


def _register(client, django_capture_on_commit_callbacks, email="yangi@example.com"):
    """Register POST — ratelimit keshini tozalab, on_commit (email task)ni bajaradi."""
    from django.core.cache import cache

    cache.clear()  # register 5/h chelagi testlar orasida to'lib qolmasin
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("users:register"),
            {"username": "yangi", "email": email, "password1": _STRONG, "password2": _STRONG},
        )
    return resp


def _verify_link(body):
    """Email matnidan tasdiqlash yo'lini ajratib oladi."""
    import re

    match = re.search(r"(/users/verify-email/[^/\s]+/)", body)
    assert match, body
    return match.group(1)


@pytest.mark.django_db
def test_register_sends_verification_email(client, django_capture_on_commit_callbacks):
    """Acceptance: ro'yxatdan o'tishda tasdiqlash emaili fon (Celery) taskda ketadi."""
    from allauth.account.models import EmailAddress
    from django.core import mail

    resp = _register(client, django_capture_on_commit_callbacks)
    assert resp.status_code == 302
    email_address = EmailAddress.objects.get(user__username="yangi")
    assert not email_address.verified
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["yangi@example.com"]
    assert "verify-email" in mail.outbox[0].body


@pytest.mark.django_db
def test_verify_email_link_confirms(client, django_capture_on_commit_callbacks):
    """Emaildagi havola bosilsa — (user, joriy email) tasdiqlangan bo'ladi."""
    from django.core import mail

    from users.services import email_verification

    _register(client, django_capture_on_commit_callbacks)
    resp = client.get(_verify_link(mail.outbox[0].body))
    assert resp.status_code == 302
    user = User.objects.get(username="yangi")
    assert email_verification.is_verified(user)


@pytest.mark.django_db
def test_verify_email_bad_key_rejected(client):
    """Buzilgan/soxta kalit hech narsani tasdiqlamaydi (BadSignature yutiladi)."""
    from users.services import email_verification

    user = _user("badkey")
    user.email = "badkey@example.com"
    user.save()
    resp = client.get("/users/verify-email/soxta-kalit/")
    assert resp.status_code == 302
    assert not email_verification.is_verified(user)


@pytest.mark.django_db
def test_email_change_resets_verification(client, django_capture_on_commit_callbacks):
    """Sozlamalarda email o'zgarsa — tasdiq avtomatik bekor, yangi havola ketadi."""
    from allauth.account.models import EmailAddress
    from django.core import mail

    from users.services import email_verification

    user = _user("almash")
    user.email = "eski@example.com"
    user.save()
    EmailAddress.objects.create(user=user, email="eski@example.com", verified=True)
    assert email_verification.is_verified(user)

    client.force_login(user)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("users:settings"),
            {"username": "almash", "email": "yangi2@example.com"},
        )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email == "yangi2@example.com"
    assert not email_verification.is_verified(user)  # yangi juftlik uchun yozuv yo'q
    assert any(m.to == ["yangi2@example.com"] for m in mail.outbox)


@pytest.mark.django_db
def test_resend_verification_sends_mail(client, django_capture_on_commit_callbacks):
    """Settings'dagi "qayta yuborish" tugmasi yangi havola jo'natadi."""
    from django.core import mail
    from django.core.cache import cache

    cache.clear()  # resend_verify 3/h chelagi
    user = _user("qayta")
    user.email = "qayta@example.com"
    user.save()
    client.force_login(user)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("users:resend_verification"))
    assert resp.status_code == 302
    assert len(mail.outbox) == 1
    cache.clear()


@pytest.mark.django_db
@pytest.mark.parametrize("bad", ["qisqa", "password", "84619375"])
def test_register_rejects_weak_password(client, bad):
    """Parol siyosati [P6-T1]: qisqa / keng tarqalgan / faqat-raqam parollar rad."""
    from django.core.cache import cache

    cache.clear()
    resp = client.post(
        reverse("users:register"),
        {"username": "zaif", "email": "zaif@example.com", "password1": bad, "password2": bad},
    )
    assert resp.status_code == 200  # forma xatolar bilan qayta ochiladi
    assert not User.objects.filter(username="zaif").exists()
    cache.clear()


@pytest.mark.django_db
def test_register_rejects_duplicate_email(client):
    """Email unikal (katta-kichik harfga befarq) — ikkinchi hisob ochilmaydi."""
    from django.core.cache import cache

    cache.clear()
    User.objects.create_user(username="birinchi", email="dup@example.com", password=_STRONG)
    resp = client.post(
        reverse("users:register"),
        {
            "username": "ikkinchi",
            "email": "DUP@example.com",
            "password1": _STRONG,
            "password2": _STRONG,
        },
    )
    assert resp.status_code == 200
    assert not User.objects.filter(username="ikkinchi").exists()
    cache.clear()


def _reset_confirm_link(body):
    """Parol tiklash emailidan confirm yo'lini ajratib oladi."""
    import re

    match = re.search(r"(/users/password-reset/[^/\s]+/[^/\s]+/)", body)
    assert match, body
    return match.group(1)


@pytest.mark.django_db
def test_password_reset_full_flow(client):
    """To'liq oqim: so'rov -> emaildagi havola -> yangi parol -> login ishlaydi."""
    from django.core import mail
    from django.core.cache import cache

    cache.clear()  # password_reset 5/h chelagi
    User.objects.create_user(username="resetchi", email="r@example.com", password="Eski-Parol-99")
    resp = client.post(reverse("users:password_reset"), {"email": "r@example.com"})
    assert resp.status_code == 302
    assert len(mail.outbox) == 1  # Celery eager — darhol outbox'da

    resp = client.get(_reset_confirm_link(mail.outbox[0].body))
    assert resp.status_code == 302  # token sessiyaga olinib set-password'ga redirect
    resp = client.post(
        resp.url, {"new_password1": "Yangi-Parol-77", "new_password2": "Yangi-Parol-77"}
    )
    assert resp.status_code == 302
    assert client.login(username="resetchi", password="Yangi-Parol-77")
    cache.clear()


@pytest.mark.django_db
def test_password_reset_rejects_weak_password(client):
    """Confirm bosqichida ham parol siyosati ishlaydi (SetPasswordForm)."""
    from django.core import mail
    from django.core.cache import cache

    cache.clear()
    User.objects.create_user(username="zaifreset", email="z@example.com", password="Eski-Parol-99")
    client.post(reverse("users:password_reset"), {"email": "z@example.com"})
    resp = client.get(_reset_confirm_link(mail.outbox[0].body))
    resp = client.post(resp.url, {"new_password1": "123", "new_password2": "123"})
    assert resp.status_code == 200  # forma xato bilan qaytadi
    assert client.login(username="zaifreset", password="Eski-Parol-99")  # eski parol joyida
    cache.clear()


@pytest.mark.django_db
def test_password_reset_unknown_email_silent(client):
    """Mavjud bo'lmagan email — baribir 'yuborildi' sahifasi, xat esa ketmaydi
    (hisob mavjudligi oshkor qilinmaydi)."""
    from django.core import mail
    from django.core.cache import cache

    cache.clear()
    resp = client.post(reverse("users:password_reset"), {"email": "yoq@example.com"})
    assert resp.status_code == 302
    assert len(mail.outbox) == 0
    cache.clear()


@pytest.mark.django_db
def test_verification_templates_render(client):
    """Smoke: settings badge (ikkala holat), login havolasi, reset sahifalari render bo'ladi."""
    from allauth.account.models import EmailAddress
    from django.core.cache import cache

    cache.clear()
    user = _user("smoke")
    user.email = "smoke@example.com"
    user.save()
    client.force_login(user)

    resp = client.get(reverse("users:settings"))
    assert resp.status_code == 200
    assert "tasdiqlanmagan" in resp.content.decode().lower()

    EmailAddress.objects.create(user=user, email="smoke@example.com", verified=True)
    resp = client.get(reverse("users:settings"))
    assert "email tasdiqlangan" in resp.content.decode().lower()

    assert client.get(reverse("users:password_reset")).status_code == 200
    resp = client.get(reverse("users:login"))
    assert "password-reset" in resp.content.decode()
    cache.clear()


# --- P7-T1: reja-asosli obuna (SubscriptionPlan/Subscription) ---


def _plan(price=15, days=30, **kwargs):
    from users.models import SubscriptionPlan

    return SubscriptionPlan.objects.create(
        name=kwargs.pop("name", f"Test reja {price}"),
        price_coins=price,
        duration_days=days,
        **kwargs,
    )


@pytest.mark.django_db
def test_purchase_creates_active_subscription():
    """Xarid: ACTIVE obuna + ledger VIP debet + profil keshi sinxron."""
    from users.models import Subscription
    from users.services import subscriptions

    user = _user("obunachi", balance=100)
    plan = _plan(price=20, days=30)
    sub = subscriptions.purchase(user.profile, plan)

    assert sub.status == Subscription.Status.ACTIVE
    user.profile.refresh_from_db()
    assert user.profile.balance == 80
    assert user.profile.is_premium is True
    assert user.profile.premium_until == sub.end_at
    txn = CoinTransaction.objects.get(profile=user.profile, type="vip")
    assert txn.amount == -20
    assert txn.reference == f"subscription:{sub.pk}"


@pytest.mark.django_db
def test_purchase_insufficient_is_atomic():
    """Balans yetmasa HECH NARSA yozilmaydi (obuna qatori ham)."""
    from users.models import Subscription
    from users.services import subscriptions, wallet

    user = _user("kambagal", balance=5)
    plan = _plan(price=20)
    with pytest.raises(wallet.InsufficientFundsError):
        subscriptions.purchase(user.profile, plan)
    user.profile.refresh_from_db()
    assert user.profile.balance == 5
    assert user.profile.is_premium is False
    assert not Subscription.objects.filter(profile=user.profile).exists()


@pytest.mark.django_db
def test_purchase_extends_active_subscription():
    """Aktiv obunada qayta xarid — YANGI qator emas, end_at uzayadi (eski semantika)."""
    from users.models import Subscription
    from users.services import subscriptions

    user = _user("uzaytiruvchi", balance=100)
    plan = _plan(price=10, days=30)
    first = subscriptions.purchase(user.profile, plan)
    second = subscriptions.purchase(user.profile, plan)

    assert first.pk == second.pk
    assert Subscription.objects.filter(profile=user.profile).count() == 1
    assert (second.end_at - second.start_at).days == 60
    user.profile.refresh_from_db()
    assert user.profile.balance == 80
    assert user.profile.premium_until == second.end_at


@pytest.mark.django_db
def test_purchase_lifetime_blocked():
    """Muddatsiz (end_at=None) obunada xarid rad — coin yechilmaydi."""
    from django.utils import timezone

    from users.models import Subscription
    from users.services import subscriptions

    user = _user("cheksiz", balance=100)
    plan = _plan()
    Subscription.objects.create(
        profile=user.profile, plan=plan, start_at=timezone.now(), end_at=None
    )
    with pytest.raises(subscriptions.LifetimeSubscriptionError):
        subscriptions.purchase(user.profile, plan)
    user.profile.refresh_from_db()
    assert user.profile.balance == 100
    assert not CoinTransaction.objects.filter(profile=user.profile, type="vip").exists()


@pytest.mark.django_db
def test_expire_beat_closes_expired_subscription():
    """Beat: muddati o'tgan ACTIVE -> EXPIRED, profil keshi tozalanadi."""
    from datetime import timedelta

    from django.utils import timezone

    from users.models import Subscription
    from users.tasks import expire_premium

    user = _user("tugagan")
    plan = _plan(price=15)
    now = timezone.now()
    Subscription.objects.create(
        profile=user.profile,
        plan=plan,
        start_at=now - timedelta(days=31),
        end_at=now - timedelta(days=1),
    )
    user.profile.is_premium = True
    user.profile.premium_until = now - timedelta(days=1)
    user.profile.save(update_fields=["is_premium", "premium_until"])

    assert expire_premium() == 1
    sub = Subscription.objects.get(profile=user.profile)
    assert sub.status == Subscription.Status.EXPIRED
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False
    assert user.profile.premium_until is None


@pytest.mark.django_db
def test_expire_beat_auto_renews_with_balance():
    """Beat + auto_renew + balans yetarli: davr UZLUKSIZ uzayadi, debet ledgerda."""
    from datetime import timedelta

    from django.utils import timezone

    from users.models import Subscription
    from users.tasks import expire_premium

    user = _user("avto", balance=50)
    plan = _plan(price=15, days=30)
    now = timezone.now()
    old_end = now - timedelta(hours=2)
    Subscription.objects.create(
        profile=user.profile,
        plan=plan,
        start_at=now - timedelta(days=30),
        end_at=old_end,
        auto_renew=True,
    )

    assert expire_premium() == 1
    sub = Subscription.objects.get(profile=user.profile)
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.end_at == old_end + timedelta(days=30)
    user.profile.refresh_from_db()
    assert user.profile.balance == 35
    assert user.profile.is_premium is True
    assert user.profile.premium_until == sub.end_at
    txn = CoinTransaction.objects.get(profile=user.profile, type="vip")
    assert txn.amount == -15


@pytest.mark.django_db
def test_expire_beat_expires_when_balance_insufficient():
    """Beat + auto_renew, balans YETMASA: EXPIRED, balans o'zgarmaydi."""
    from datetime import timedelta

    from django.utils import timezone

    from users.models import Subscription
    from users.tasks import expire_premium

    user = _user("pulsiz", balance=5)
    plan = _plan(price=15)
    now = timezone.now()
    Subscription.objects.create(
        profile=user.profile,
        plan=plan,
        start_at=now - timedelta(days=30),
        end_at=now - timedelta(hours=1),
        auto_renew=True,
    )

    assert expire_premium() == 1
    sub = Subscription.objects.get(profile=user.profile)
    assert sub.status == Subscription.Status.EXPIRED
    user.profile.refresh_from_db()
    assert user.profile.balance == 5
    assert user.profile.is_premium is False


@pytest.mark.django_db
def test_expire_beat_legacy_profile_without_subscription():
    """Obunasiz legacy premium — eski xatti-harakat saqlangan: muddat o'tsa o'chadi."""
    from datetime import timedelta

    from django.utils import timezone

    from users.tasks import expire_premium

    user = _user("legacy")
    user.profile.is_premium = True
    user.profile.premium_until = timezone.now() - timedelta(days=1)
    user.profile.save(update_fields=["is_premium", "premium_until"])

    assert expire_premium() == 1
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False


@pytest.mark.django_db
def test_buy_premium_view_plan_and_auto_renew(client):
    """POST plan+auto_renew: tanlangan reja bo'yicha obuna, flag saqlanadi."""
    from users.models import Subscription

    user = _user("tanlagan", balance=100)
    client.force_login(user)
    plan = _plan(price=40, days=90, name="VIP 3 oy")
    resp = client.post(reverse("users:buy_premium"), {"plan": plan.pk, "auto_renew": "on"})
    assert resp.status_code == 302
    sub = Subscription.objects.get(profile=user.profile)
    assert sub.plan == plan
    assert sub.auto_renew is True
    user.profile.refresh_from_db()
    assert user.profile.balance == 60
    assert user.profile.is_premium is True


@pytest.mark.django_db
def test_subscription_page_lists_plans(client):
    """Sahifa rejalarni DB'dan ko'rsatadi (seed 'VIP 1 oy' ham) — render smoke."""
    _plan(name="Maxsus reja", price=25)
    resp = client.get(reverse("users:subscription"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Maxsus reja" in body
    assert "VIP 1 oy" in body  # 0015 seed migratsiyasidan


@pytest.mark.django_db
def test_toggle_auto_renew_view(client):
    """Aktiv obunada avto-uzaytirish POST bilan almashtiriladi."""
    from users.models import Subscription
    from users.services import subscriptions

    user = _user("toggler", balance=50)
    client.force_login(user)
    plan = _plan(price=10)
    subscriptions.purchase(user.profile, plan)

    resp = client.post(reverse("users:toggle_auto_renew"))
    assert resp.status_code == 302
    assert Subscription.objects.get(profile=user.profile).auto_renew is True
