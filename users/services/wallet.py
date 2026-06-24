"""Coin hamyon ledgeri — balansni o'zgartiruvchi YAGONA xavfsiz nuqta.

Har bir coin harakati `CoinTransaction` sifatida yoziladi (o'zgarmas audit izi).
Invariant: ``profile.balance == SUM(CoinTransaction.amount)``.

Barcha kredit/debet shu modul orqali o'tadi (topup, sovg'a, funding, VIP, refund).
Balansni hech qachon to'g'ridan-to'g'ri ``profile.balance += ...`` bilan o'zgartirmang.
"""

from __future__ import annotations

from django.db import transaction

from users.models import CoinTransaction, Profile


class InsufficientFundsError(Exception):
    """Debet balansni manfiyga tushiradi va ``allow_negative`` berilmagan."""


@transaction.atomic
def _apply(
    profile: Profile,
    amount: int,
    txn_type: str,
    *,
    description: str = "",
    reference: str = "",
    allow_negative: bool = False,
) -> CoinTransaction:
    """Atomik tarzda balansni o'zgartiradi va ledger yozuvini yaratadi.

    ``select_for_update`` profil qatorini qulflaydi — parallel so'rovlar
    balansni buzmasligi (race / double-spend) uchun.
    """
    locked = Profile.objects.select_for_update().get(pk=profile.pk)
    new_balance = locked.balance + amount
    if new_balance < 0 and not allow_negative:
        raise InsufficientFundsError(f"Balans yetarli emas: {locked.balance} + ({amount}) < 0")

    locked.balance = new_balance
    locked.save(update_fields=["balance"])
    # Chaqiruvchidagi obyekt ham yangilansin (eskirgan balans ko'rsatmasligi uchun).
    profile.balance = new_balance

    return CoinTransaction.objects.create(
        profile=locked,
        amount=amount,
        type=txn_type,
        balance_after=new_balance,
        description=description,
        reference=reference,
    )


def credit(
    profile: Profile,
    amount: int,
    txn_type: str,
    *,
    description: str = "",
    reference: str = "",
    allow_negative: bool = False,
) -> CoinTransaction:
    """Balansga coin qo'shadi. ``amount`` musbat bo'lishi shart."""
    if amount <= 0:
        raise ValueError("credit() uchun amount musbat bo'lishi kerak")
    return _apply(
        profile,
        amount,
        txn_type,
        description=description,
        reference=reference,
        allow_negative=allow_negative,
    )


def debit(
    profile: Profile,
    amount: int,
    txn_type: str,
    *,
    description: str = "",
    reference: str = "",
    allow_negative: bool = False,
) -> CoinTransaction:
    """Balansdan coin yechadi. ``amount`` musbat beriladi, ledgerga manfiy yoziladi."""
    if amount <= 0:
        raise ValueError("debit() uchun amount musbat bo'lishi kerak")
    return _apply(
        profile,
        -amount,
        txn_type,
        description=description,
        reference=reference,
        allow_negative=allow_negative,
    )
