"""Obuna (reja-asosli VIP) servisi [P7-T1] — obuna o'zgartiruvchi YAGONA nuqta.

Haqiqat manbai: Subscription qatorlari. Profile.is_premium/premium_until KESH
(gating/shablonlar O(1) o'qiydi) — har o'zgarishda _sync_profile_cache()
yangilaydi. Obunasiz profillardagi qo'lda berilgan legacy premium TEGILMAYDI.

Coin harakati faqat wallet (ledger) orqali — balansni to'g'ridan-to'g'ri
o'zgartirish taqiqlangan (P1-T4 invarianti).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from users.models import CoinTransaction, Profile, Subscription, SubscriptionPlan
from users.services import wallet


class LifetimeSubscriptionError(Exception):
    """Profilda muddatsiz (end_at=None) obuna bor — xarid ma'nosiz, coin yechilmaydi."""


def _q_not_expired(now):
    """end_at hali kelmagan YOKI muddatsiz (None) obunalar sharti."""
    return Q(end_at__isnull=True) | Q(end_at__gt=now)


def active_subscription(profile: Profile) -> Subscription | None:
    """Profilning ACTIVE obunasi (beat hali yopmagan eskirganini ham qaytaradi)."""
    return (
        profile.subscriptions.filter(status=Subscription.Status.ACTIVE)
        .select_related("plan")
        .first()
    )


def _sync_profile_cache(profile: Profile) -> None:
    """Profile.is_premium/premium_until keshini ACTIVE obunadan qayta yozadi.

    Faqat obunasi BOR profillarda chaqiriladi — legacy (obunasiz) premium
    profillarga bu funksiya umuman tegmaydi.
    """
    now = timezone.now()
    sub = (
        profile.subscriptions.filter(status=Subscription.Status.ACTIVE)
        .filter(_q_not_expired(now))
        .first()
    )
    if sub is not None:
        profile.is_premium = True
        profile.premium_until = sub.end_at
    else:
        profile.is_premium = False
        profile.premium_until = None
    profile.save(update_fields=["is_premium", "premium_until"])


@transaction.atomic
def purchase(profile: Profile, plan: SubscriptionPlan, *, auto_renew: bool = False) -> Subscription:
    """Coin evaziga obuna sotib olish/uzaytirish — atomik, ledger orqali.

    Qoida (eski buy_premium semantikasi saqlangan):
    - aktiv obuna bor (end_at kelajakda) -> end_at += plan.duration (uzaytirish);
    - aktiv qator eskirgan (beat hali yopmagan) -> u EXPIRED, yangi davr ochiladi;
    - aktiv obuna yo'q -> yangi Subscription(start=now, end=now+duration).
    InsufficientFundsError'da butun tranzaksiya orqaga qaytadi (hech narsa yozilmaydi).
    """
    now = timezone.now()
    sub = (
        profile.subscriptions.select_for_update().filter(status=Subscription.Status.ACTIVE).first()
    )

    if sub is not None and sub.end_at is None:
        raise LifetimeSubscriptionError("Sizda muddatsiz VIP mavjud — xarid shart emas.")

    if sub is not None and sub.end_at > now:
        sub.end_at += timedelta(days=plan.duration_days)
        sub.plan = plan  # oxirgi xarid rejasi ko'rsatiladi; narxlar tarixi ledgerda
        sub.auto_renew = auto_renew or sub.auto_renew
        sub.save(update_fields=["end_at", "plan", "auto_renew", "updated_at"])
    else:
        if sub is not None:  # eskirgan-lekin-yopilmagan qator — tarixga o'tadi
            sub.status = Subscription.Status.EXPIRED
            sub.save(update_fields=["status", "updated_at"])
        sub = Subscription.objects.create(
            profile=profile,
            plan=plan,
            start_at=now,
            end_at=now + timedelta(days=plan.duration_days),
            auto_renew=auto_renew,
        )

    wallet.debit(
        profile,
        plan.price_coins,
        CoinTransaction.Type.VIP,
        description=f"{plan.name} obunasi ({plan.duration_days} kun)",
        reference=f"subscription:{sub.pk}",
    )
    _sync_profile_cache(profile)
    return sub


def cancel(sub: Subscription) -> None:
    """Obunani bekor qiladi (admin action) va profil keshini sinxronlaydi.

    Coin qaytarilmaydi — refund kerak bo'lsa admin wallet orqali alohida qiladi.
    """
    sub.status = Subscription.Status.CANCELED
    sub.save(update_fields=["status", "updated_at"])
    _sync_profile_cache(sub.profile)


def close_or_renew(sub: Subscription) -> str:
    """Muddati o'tgan ACTIVE obunani yopadi yoki (auto_renew) uzaytiradi.

    Beat task (users/tasks.expire_premium) chaqiradi. Qaytaradi: "renewed"|"expired".
    Auto-renew: davr uzluksiz (yangi end = eski end + duration); balans yetmasa
    EXPIRED. Reja sotuvdan olingan bo'lsa ham renew davom etadi (obuna shartnomasi).
    """
    with transaction.atomic():
        locked = (
            Subscription.objects.select_for_update()
            .select_related("plan", "profile")
            .get(pk=sub.pk)
        )
        now = timezone.now()
        # Idempotentlik: parallel beat/xarid allaqachon hal qilgan bo'lishi mumkin
        if locked.status != Subscription.Status.ACTIVE or locked.end_at is None:
            return "skipped"
        if locked.end_at > now:
            return "skipped"

        if locked.auto_renew:
            try:
                # Avval debit (yetmasa hech narsa yozilmagan holda exception),
                # keyin end_at — aks holda savepoint faqat debit'ni qaytarib,
                # uzaytirilgan end_at tashqi tranzaksiyada qolib ketardi.
                wallet.debit(
                    locked.profile,
                    locked.plan.price_coins,
                    CoinTransaction.Type.VIP,
                    description=f"{locked.plan.name} avto-uzaytirish",
                    reference=f"subscription:{locked.pk}",
                )
                locked.end_at += timedelta(days=locked.plan.duration_days)
                locked.save(update_fields=["end_at", "updated_at"])
                _sync_profile_cache(locked.profile)
                return "renewed"
            except wallet.InsufficientFundsError:
                pass  # balans yetmadi — quyida EXPIRED

        locked.status = Subscription.Status.EXPIRED
        locked.save(update_fields=["status", "updated_at"])
        _sync_profile_cache(locked.profile)
        return "expired"
