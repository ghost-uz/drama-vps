"""billing/providers/payme.py — Payme Merchant API (JSON-RPC 2.0) [P7-T2].

Payme merchant endpoint'imizga chaqiradi (webhook EMAS, so'rov-javob RPC).
Autentifikatsiya: HTTP Basic — login "Paycom", parol = settings.PAYME_KEY.
Summa TIYINDA (1 UZS = 100 tiyin). Hisobvaraq (account): {"order_id": "<uuid>"}.

Holat mashinasi (Order.provider_state): 1=yaratilgan, 2=to'langan, -1=to'lovsiz
bekor, -2=to'langandan keyin bekor. Bu qiymatlar Payme spetsifikatsiyasi.

Idempotentlik: har metod bir necha marta chaqirilsa ham bir xil natija (Coin
kreditlash faqat services.mark_paid — select_for_update + holat-gvardi).
"""

from __future__ import annotations

import base64
from datetime import UTC

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from billing import services
from billing.models import Order

# Merchant tranzaksiyasi eskirish muddati (Payme spec: 12 soat)
TRANSACTION_TIMEOUT_MS = 12 * 60 * 60 * 1000

# Payme holatlari
STATE_CREATED = 1
STATE_PERFORMED = 2
STATE_CANCELED = -1
STATE_CANCELED_AFTER_PERFORM = -2


class PaymeError(Exception):
    """JSON-RPC xato — Payme kutgan {code, message, data} formatida qaytadi."""

    def __init__(self, code: int, message, data: str | None = None):
        self.code = code
        # Payme lokalizatsiyalangan xabar kutadi (ru/uz/en)
        self.message = (
            message if isinstance(message, dict) else {"ru": message, "uz": message, "en": message}
        )
        self.data = data
        super().__init__(str(message))


# Standart xato konstruktorlari (kod + uch tilli xabar)
def _err_order_not_found() -> PaymeError:
    return PaymeError(
        -31050,
        {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
        data="order_id",
    )


def _err_invalid_amount() -> PaymeError:
    return PaymeError(
        -31001, {"ru": "Неверная сумма", "uz": "Noto'g'ri summa", "en": "Invalid amount"}
    )


def _err_txn_not_found() -> PaymeError:
    return PaymeError(
        -31003,
        {
            "ru": "Транзакция не найдена",
            "uz": "Tranzaksiya topilmadi",
            "en": "Transaction not found",
        },
    )


def _err_cannot_perform() -> PaymeError:
    return PaymeError(
        -31008,
        {
            "ru": "Невозможно выполнить операцию",
            "uz": "Amalni bajarib bo'lmaydi",
            "en": "Unable to perform operation",
        },
    )


def check_auth(auth_header: str | None) -> bool:
    """HTTP Basic sarlavhasini tekshiradi: login "Paycom", parol PAYME_KEY."""
    key = settings.PAYME_KEY
    if not key or not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _, _, password = decoded.partition(":")
    return password == key


def _ms(dt) -> int:
    """datetime -> Payme kutgan millisekund timestamp (yo'q bo'lsa 0)."""
    return int(dt.timestamp() * 1000) if dt else 0


def _get_order_by_account(params) -> Order:
    account = params.get("account") or {}
    order_id = account.get("order_id")
    if not order_id:
        raise _err_order_not_found()
    try:
        return Order.objects.get(pk=order_id, provider=Order.Provider.PAYME)
    except (Order.DoesNotExist, ValueError, ValidationError):
        raise _err_order_not_found() from None


def _get_order_by_txn(params) -> Order:
    txn_id = params.get("id")
    order = Order.objects.filter(provider=Order.Provider.PAYME, provider_txn_id=txn_id).first()
    if order is None:
        raise _err_txn_not_found()
    return order


def _account_error_if_unpayable(order: Order, amount: int) -> None:
    """CheckPerformTransaction/CreateTransaction umumiy tekshiruvi."""
    if amount != order.amount_tiyin:
        raise _err_invalid_amount()
    if order.status != Order.Status.CREATED:
        # Allaqachon to'langan/bekor — yangi tranzaksiyaga yaroqsiz
        raise _err_cannot_perform()


# ── RPC metod handlerlari ────────────────────────────────────────────────


def check_perform_transaction(params) -> dict:
    order = _get_order_by_account(params)
    _account_error_if_unpayable(order, params.get("amount"))
    return {"allow": True}


def create_transaction(params) -> dict:
    txn_id = params.get("id")
    order = _get_order_by_account(params)

    # Idempotent: shu order'da AYNAN shu tranzaksiya allaqachon bor -> qaytaramiz
    if order.provider_txn_id == txn_id:
        if order.provider_state != STATE_CREATED:
            raise _err_cannot_perform()
        return {
            "create_time": _ms(order.provider_created_at),
            "transaction": str(order.id),
            "state": STATE_CREATED,
        }

    # Order boshqa faol tranzaksiya bilan band bo'lsa yangi ochib bo'lmaydi
    if order.provider_txn_id:
        raise _err_cannot_perform()

    _account_error_if_unpayable(order, params.get("amount"))

    order.provider_txn_id = txn_id
    order.provider_state = STATE_CREATED
    order.provider_created_at = timezone.now()
    order.save(update_fields=["provider_txn_id", "provider_state", "provider_created_at"])
    return {
        "create_time": _ms(order.provider_created_at),
        "transaction": str(order.id),
        "state": STATE_CREATED,
    }


def perform_transaction(params) -> dict:
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(provider=Order.Provider.PAYME, provider_txn_id=params.get("id"))
            .first()
        )
        if order is None:
            raise _err_txn_not_found()

        if order.provider_state == STATE_PERFORMED:
            return {  # idempotent
                "transaction": str(order.id),
                "perform_time": _ms(order.paid_at),
                "state": STATE_PERFORMED,
            }
        if order.provider_state != STATE_CREATED:
            raise _err_cannot_perform()

        # Eskirgan tranzaksiya (12 soat) -> bekor va xato
        if _ms(timezone.now()) - _ms(order.provider_created_at) > TRANSACTION_TIMEOUT_MS:
            order.provider_state = STATE_CANCELED
            order.cancel_reason = 4  # Payme: muddat tugadi
            order.canceled_at = timezone.now()
            order.status = Order.Status.CANCELED
            order.save(update_fields=["provider_state", "cancel_reason", "canceled_at", "status"])
            raise _err_cannot_perform()

        order.provider_state = STATE_PERFORMED
        order.save(update_fields=["provider_state"])
        # Coin kreditlash — YAGONA nuqta (idempotent, ledger orqali)
        services.mark_paid(order.id)
        order.refresh_from_db()

    return {
        "transaction": str(order.id),
        "perform_time": _ms(order.paid_at),
        "state": STATE_PERFORMED,
    }


def cancel_transaction(params) -> dict:
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(provider=Order.Provider.PAYME, provider_txn_id=params.get("id"))
            .first()
        )
        if order is None:
            raise _err_txn_not_found()

        # Allaqachon bekor qilingan -> joriy holatni qaytaramiz (idempotent)
        if order.provider_state in (STATE_CANCELED, STATE_CANCELED_AFTER_PERFORM):
            return {
                "transaction": str(order.id),
                "cancel_time": _ms(order.canceled_at),
                "state": order.provider_state,
            }

        new_state = (
            STATE_CANCELED_AFTER_PERFORM
            if order.provider_state == STATE_PERFORMED
            else STATE_CANCELED
        )
        order.provider_state = new_state
        order.cancel_reason = params.get("reason")
        order.canceled_at = timezone.now()
        order.save(update_fields=["provider_state", "cancel_reason", "canceled_at"])
        # To'langan bo'lsa Coin qaytariladi (refund, ledger orqali)
        services.mark_canceled(order.id)
        order.refresh_from_db()

    return {
        "transaction": str(order.id),
        "cancel_time": _ms(order.canceled_at),
        "state": new_state,
    }


def check_transaction(params) -> dict:
    order = _get_order_by_txn(params)
    return {
        "create_time": _ms(order.provider_created_at),
        "perform_time": _ms(order.paid_at),
        "cancel_time": _ms(order.canceled_at),
        "transaction": str(order.id),
        "state": order.provider_state,
        "reason": order.cancel_reason,
    }


def get_statement(params) -> dict:
    from datetime import datetime

    start = datetime.fromtimestamp(params.get("from", 0) / 1000, tz=UTC)
    end = datetime.fromtimestamp(params.get("to", 0) / 1000, tz=UTC)
    orders = Order.objects.filter(
        provider=Order.Provider.PAYME,
        provider_created_at__gte=start,
        provider_created_at__lte=end,
    ).exclude(provider_txn_id="")
    return {
        "transactions": [
            {
                "id": o.provider_txn_id,
                "time": _ms(o.provider_created_at),
                "amount": o.amount_tiyin,
                "account": {"order_id": str(o.id)},
                "create_time": _ms(o.provider_created_at),
                "perform_time": _ms(o.paid_at),
                "cancel_time": _ms(o.canceled_at),
                "transaction": str(o.id),
                "state": o.provider_state,
                "reason": o.cancel_reason,
            }
            for o in orders
        ]
    }


_METHODS = {
    "CheckPerformTransaction": check_perform_transaction,
    "CreateTransaction": create_transaction,
    "PerformTransaction": perform_transaction,
    "CancelTransaction": cancel_transaction,
    "CheckTransaction": check_transaction,
    "GetStatement": get_statement,
}


def handle(method: str, params: dict) -> dict:
    """Metodni bajaradi; noma'lum metod -> PaymeError(-32601)."""
    handler = _METHODS.get(method)
    if handler is None:
        raise PaymeError(
            -32601, {"ru": "Метод не найден", "uz": "Metod topilmadi", "en": "Method not found"}
        )
    return handler(params)


def checkout_url(order: Order, return_url: str = "") -> str:
    """Payme checkout (to'lov sahifasi) URL'i — GET redirect uchun [P7-T2].

    Format: base64("m=<merchant>;ac.order_id=<id>;a=<tiyin>;c=<return>").
    Merchant ID sozlanmagan bo'lsa bo'sh string (dev fallback).
    """
    merchant_id = settings.PAYME_MERCHANT_ID
    if not merchant_id:
        return ""
    parts = f"m={merchant_id};ac.order_id={order.id};a={order.amount_tiyin}"
    if return_url:
        parts += f";c={return_url}"
    encoded = base64.b64encode(parts.encode("utf-8")).decode("ascii")
    return f"{settings.PAYME_CHECKOUT_URL}/{encoded}"
