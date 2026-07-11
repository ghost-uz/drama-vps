"""funding app testlari [P7-T4] — atomik hissa, goal-transition, refund, admin guard.

View-darajali bazaviy oqimlar (ledger debet, minimal summa, insufficient-atomiklik,
access) users/tests.py'da P1-T4 davridan beri bor — bu fayl P7-T4 qo'shgan
servis-qatlam kafolatlarini qamraydi.
"""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from funding import services
from funding.factories import FundingProjectFactory
from funding.models import FundingContributor, FundingProject
from users.factories import UserFactory
from users.models import CoinTransaction, Notification
from users.services import wallet


def _profile(balance=200):
    """Balansli profil (test-setup: to'g'ridan, ledger'siz — users/tests.py uslubi)."""
    user = UserFactory()
    profile = user.profile
    profile.balance = balance
    profile.save(update_fields=["balance"])
    return profile


# --- contribute: goal-transition ---


@pytest.mark.django_db
def test_contribute_goal_reached_sets_translating_and_notifies():
    """Maqsadga yetganda status o'zi TRANSLATING bo'ladi, hissadorlarga xabar ketadi."""
    project = FundingProjectFactory(target_amount=100)
    p1, p2 = _profile(), _profile()

    services.contribute(p1, project.pk, 60)
    project.refresh_from_db()
    assert project.status == FundingProject.Status.FUNDING  # 60 < 100 — hali erta

    services.contribute(p2, project.pk, 50)  # 110 >= 100
    project.refresh_from_db()
    assert project.status == FundingProject.Status.TRANSLATING
    assert project.collected_amount == 110

    notes = Notification.objects.filter(kind=Notification.Kind.FUNDING)
    assert notes.count() == 2  # ikkala hissadorga bittadan (distinct fan-out)
    assert {n.recipient_id for n in notes} == {p1.user_id, p2.user_id}
    assert all(n.url == project.movie.get_absolute_url() for n in notes)


@pytest.mark.django_db
def test_contribute_exact_target_reaches_goal():
    project = FundingProjectFactory(target_amount=100)
    services.contribute(_profile(), project.pk, 100)
    project.refresh_from_db()
    assert project.status == FundingProject.Status.TRANSLATING


# --- contribute: holat gvardilari ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [FundingProject.Status.TRANSLATING, FundingProject.Status.CANCELED]
)
def test_contribute_rejected_when_not_accepting(status):
    """Yopiq holatlarda hissa rad — hech narsa yozilmaydi."""
    project = FundingProjectFactory(status=status)
    profile = _profile()
    with pytest.raises(services.NotAcceptingContributions):
        services.contribute(profile, project.pk, 60)
    project.refresh_from_db()
    profile.refresh_from_db()
    assert project.collected_amount == 0
    assert FundingContributor.objects.count() == 0
    assert profile.balance == 200


@pytest.mark.django_db
def test_contribute_below_minimum_raises():
    project = FundingProjectFactory()  # min_fund_amount default 50
    with pytest.raises(services.BelowMinimum):
        services.contribute(_profile(), project.pk, 10)
    assert FundingContributor.objects.count() == 0


@pytest.mark.django_db
def test_contribute_insufficient_funds_rolls_back():
    """Ledger debet yiqilsa collected/contributor ham yozilmaydi (bitta tranzaksiya)."""
    project = FundingProjectFactory()
    profile = _profile(balance=10)
    with pytest.raises(wallet.InsufficientFundsError):
        services.contribute(profile, project.pk, 60)
    project.refresh_from_db()
    assert project.collected_amount == 0
    assert FundingContributor.objects.count() == 0


# --- contribute: released (sotib olish) ---


@pytest.mark.django_db
def test_released_purchase_fixed_price_and_no_double_charge():
    """Narx qat'iy (kiritilgan summa e'tiborsiz); qayta xarid qulf ichida rad."""
    project = FundingProjectFactory(status=FundingProject.Status.RELEASED, post_release_price=100)
    profile = _profile(balance=250)

    contribution = services.contribute(profile, project.pk, 5)
    assert contribution.amount_paid == 100
    profile.refresh_from_db()
    project.refresh_from_db()
    assert profile.balance == 150
    assert project.collected_amount == 100
    assert project.has_access(profile)

    with pytest.raises(services.AlreadyPurchased):
        services.contribute(profile, project.pk, 5)
    profile.refresh_from_db()
    assert profile.balance == 150  # double-charge yo'q


@pytest.mark.django_db
def test_view_released_purchase_charges_fixed_price(client):
    """View -> servis ulanishi: released'da post_release_price yechiladi."""
    project = FundingProjectFactory(status=FundingProject.Status.RELEASED, post_release_price=100)
    profile = _profile(balance=150)
    client.force_login(profile.user)
    resp = client.post(reverse("funding:process", args=[project.pk]), {"amount": "1"})
    assert resp.status_code == 302
    profile.refresh_from_db()
    assert profile.balance == 50


# --- cancel_project: refund ---


@pytest.mark.django_db
def test_cancel_refunds_active_contributions_and_notifies():
    """Barcha faol hissa qaytadi (bir user ko'p hissa ham), access yopiladi."""
    project = FundingProjectFactory(target_amount=1000)
    p1, p2 = _profile(balance=300), _profile(balance=100)
    services.contribute(p1, project.pk, 60)
    services.contribute(p1, project.pk, 70)  # bitta user ikki hissa
    services.contribute(p2, project.pk, 50)

    refunded = services.cancel_project(project.pk)

    assert refunded == 3
    project.refresh_from_db()
    p1.refresh_from_db()
    p2.refresh_from_db()
    assert project.status == FundingProject.Status.CANCELED
    assert p1.balance == 300 and p2.balance == 100  # to'liq qaytdi
    assert project.contributors.filter(refunded_at__isnull=True).count() == 0
    assert not project.has_access(p1)  # gating qayta yopildi

    refund_txns = CoinTransaction.objects.filter(type=CoinTransaction.Type.REFUND)
    assert refund_txns.count() == 3
    assert all(t.reference.startswith(f"funding-refund:{project.pk}:") for t in refund_txns)

    notes = Notification.objects.filter(kind=Notification.Kind.FUNDING)
    assert notes.count() == 2  # distinct userlarga (3 hissa emas, 2 user)
    assert {n.recipient_id for n in notes} == {p1.user_id, p2.user_id}


@pytest.mark.django_db
def test_cancel_idempotent_no_double_refund():
    project = FundingProjectFactory()
    profile = _profile(balance=100)
    services.contribute(profile, project.pk, 60)

    assert services.cancel_project(project.pk) == 1
    assert services.cancel_project(project.pk) == 0  # takror — hech narsa

    profile.refresh_from_db()
    assert profile.balance == 100  # faqat BIR marta qaytgan
    assert CoinTransaction.objects.filter(type=CoinTransaction.Type.REFUND).count() == 1
    assert Notification.objects.filter(kind=Notification.Kind.FUNDING).count() == 1


@pytest.mark.django_db
def test_cancel_released_project_forbidden():
    """Chiqarilgan loyiha bekor qilinmaydi — hissadorlar accessi saqlanadi."""
    project = FundingProjectFactory(status=FundingProject.Status.RELEASED)
    with pytest.raises(services.FundingError):
        services.cancel_project(project.pk)
    project.refresh_from_db()
    assert project.status == FundingProject.Status.RELEASED


# --- admin qatlami ---


@pytest.mark.django_db
def test_admin_form_blocks_manual_cancel_but_allows_other_transitions():
    from funding.admin import FundingProjectAdminForm

    project = FundingProjectFactory()
    base = {
        "movie": project.movie_id,
        "target_amount": project.target_amount,
        "collected_amount": 0,
        "min_fund_amount": 50,
        "post_release_price": 100,
    }
    blocked = FundingProjectAdminForm(
        data={**base, "status": FundingProject.Status.CANCELED}, instance=project
    )
    assert not blocked.is_valid()
    assert "status" in blocked.errors

    allowed = FundingProjectAdminForm(
        data={**base, "status": FundingProject.Status.TRANSLATING}, instance=project
    )
    assert allowed.is_valid(), allowed.errors


@pytest.mark.django_db
def test_admin_cancel_action_refunds(client):
    """Changelist action to'liq oqimi: bekor + refund + xabar."""
    admin_user = User.objects.create_superuser("boss", "b@test.uz", "pass12345")
    client.force_login(admin_user)
    project = FundingProjectFactory()
    profile = _profile(balance=100)
    services.contribute(profile, project.pk, 60)

    resp = client.post(
        reverse("admin:funding_fundingproject_changelist"),
        {"action": "cancel_and_refund", "_selected_action": [str(project.pk)]},
    )
    assert resp.status_code == 302
    project.refresh_from_db()
    profile.refresh_from_db()
    assert project.status == FundingProject.Status.CANCELED
    assert profile.balance == 100
