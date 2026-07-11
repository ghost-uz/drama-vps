"""billing/services.py — buyurtma va Coin kreditlash [P7-T2].

`mark_paid` = to'lovdan Coin'ga o'tishning YAGONA nuqtasi: select_for_update +
holat-gvardi bilan IDEMPOTENT (webhook bir necha marta kelsa ham bir marta
kredit), kredit esa faqat wallet ledger orqali (P1-T4 invarianti).

Coin narxi: 1000 UZS = 1 Coin (TopUpRequest bilan bir xil).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from billing.models import Order
from users.models import CoinTransaction
from users.services import wallet

# 1 Coin = 1000 UZS (mavjud qo'lda-topup kursi bilan mos)
UZS_PER_COIN = 1000

# Ledger turi provider bo'yicha (aniq audit izi uchun)
_LEDGER_TYPE: dict[str, CoinTransaction.Type] = {
    Order.Provider.PAYME: CoinTransaction.Type.PAYME,
    Order.Provider.CLICK: CoinTransaction.Type.CLICK,
}


def coins_for_amount(amount_uzs: int) -> int:
    """Berilgan UZS uchun Coin miqdori (butun bo'linma)."""
    return amount_uzs // UZS_PER_COIN


def create_order(user, provider: str, amount_uzs: int) -> Order:
    """Yangi CREATED buyurtma yaratadi (checkout boshlanishida)."""
    return Order.objects.create(
        user=user,
        provider=provider,
        amount_uzs=amount_uzs,
        coins=coins_for_amount(amount_uzs),
    )


def mark_paid(order_id) -> Order:
    """Buyurtmani to'langan deb belgilaydi va Coin'ni ledger orqali kreditlaydi.

    IDEMPOTENT: allaqachon PAID bo'lsa qayta kredit bermaydi (webhook takror
    kelishi normal). select_for_update — parallel webhook chaqiruvlari poygasi
    xavfsiz. Chaqiruvchi provider handleri o'z holatini (provider_state=2,
    paid_at) SHU tranzaksiya ichida allaqachon o'rnatgan bo'lishi mumkin —
    bu funksiya faqat status+ledger'ni boshqaradi.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == Order.Status.PAID:
            return order  # allaqachon kreditlangan — hech narsa qilmaymiz

        order.status = Order.Status.PAID
        if order.paid_at is None:
            order.paid_at = timezone.now()
        order.save(update_fields=["status", "paid_at"])

        wallet.credit(
            order.user.profile,
            order.coins,
            _LEDGER_TYPE[order.provider],
            description=f"{order.get_provider_display()} to'lovi ({order.amount_uzs} UZS)",
            reference=f"order:{order.id}",
        )
    return order


def mark_canceled(order_id) -> Order:
    """Buyurtmani bekor qiladi; to'langan bo'lsa Coin'ni QAYTARADI (refund).

    IDEMPOTENT: allaqachon CANCELED bo'lsa qayta refund bermaydi. Refund
    balansni manfiyga tushirishi mumkin (coin allaqachon sarflangan bo'lsa) —
    allow_negative=True (ledger invarianti buzilmaydi, P1-T4).
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == Order.Status.CANCELED:
            return order

        was_paid = order.status == Order.Status.PAID
        order.status = Order.Status.CANCELED
        if order.canceled_at is None:
            order.canceled_at = timezone.now()
        order.save(update_fields=["status", "canceled_at"])

        if was_paid:
            wallet.debit(
                order.user.profile,
                order.coins,
                CoinTransaction.Type.REFUND,
                description=f"{order.get_provider_display()} to'lovi bekor qilindi",
                reference=f"order:{order.id}",
                allow_negative=True,
            )
    return order
