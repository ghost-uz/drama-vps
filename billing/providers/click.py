"""billing/providers/click.py — Click Merchant API (Prepare/Complete) [V2F-T1].

Click Payme'dan FARQLI: JSON-RPC emas, ikkita form-encoded callback:
  * Prepare  (action=0): buyurtmani tekshirish/band qilish -> merchant_prepare_id
  * Complete (action=1): to'lovni tasdiqlash -> Coin kreditlash (yoki bekor)

Autentifikatsiya: `sign_string` = md5(maydonlar + SECRET_KEY). Summa UZS'da
(o'nlik string, masalan "1000.00"). merchant_trans_id = bizning Order UUID.

Idempotentlik va kredit: FAQAT services.mark_paid/mark_canceled (select_for_update
+ ledger, P1-T4 invarianti) — bu modul faqat protokol/imzo/holat adapteri.

Click provider_state semantikasi (Order.provider_state):
  1=prepared, 2=confirmed(paid), -1=cancelled.
"""

from __future__ import annotations

import hashlib
import hmac
import zlib
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from billing import services
from billing.models import Order

# --- Click merchant error kodlari (javob `error` maydonida qaytadi) ---
ERR_SUCCESS = 0
ERR_SIGN_CHECK = -1  # imzo mos kelmadi
ERR_INVALID_AMOUNT = -2  # summa noto'g'ri
ERR_ACTION_NOT_FOUND = -3  # action noma'lum
ERR_ALREADY_PAID = -4  # allaqachon to'langan
ERR_ORDER_NOT_FOUND = -5  # buyurtma (user) topilmadi
ERR_TXN_NOT_FOUND = -6  # tranzaksiya/prepare topilmadi
ERR_BAD_REQUEST = -8  # click so'rovidagi xato
ERR_CANCELLED = -9  # tranzaksiya bekor qilingan

# Click action kodlari
ACTION_PREPARE = 0
ACTION_COMPLETE = 1

# Order.provider_state (Click semantikasi)
STATE_PREPARED = 1
STATE_CONFIRMED = 2
STATE_CANCELLED = -1


def _md5(text: str) -> str:
    # nosec B324 — MD5 bu yerda kriptografik hash EMAS, Click merchant
    # protokoli TALAB qiladigan imzo algoritmi (o'zgartirib bo'lmaydi).
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324


def _prepare_id(order: Order) -> int:
    """Order uchun barqaror, musbat merchant_prepare_id (UUID'dan CRC32).

    Alohida ustun kerak emas: prepare'da qaytaramiz, complete'da Click uni
    aynan qaytaradi va imzoga kiradi -> imzo tekshiruvi + shu qiymat
    order'ga tegishliligini kafolatlaydi (defense-in-depth).
    """
    return zlib.crc32(str(order.id).encode("ascii")) & 0xFFFFFFFF


def check_sign(params: dict, *, is_complete: bool) -> bool:
    """Click imzosini tekshiradi (constant-time solishtirish).

    Prepare:  md5(click_trans_id + service_id + KEY + merchant_trans_id +
                  amount + action + sign_time)
    Complete: md5(click_trans_id + service_id + KEY + merchant_trans_id +
                  merchant_prepare_id + amount + action + sign_time)
    """
    key = settings.CLICK_SECRET_KEY
    got = params.get("sign_string", "")
    if not key or not got:
        return False

    fields = [
        params.get("click_trans_id", ""),
        params.get("service_id", ""),
        key,
        params.get("merchant_trans_id", ""),
    ]
    if is_complete:
        fields.append(params.get("merchant_prepare_id", ""))
    fields += [
        params.get("amount", ""),
        params.get("action", ""),
        params.get("sign_time", ""),
    ]
    expected = _md5("".join(str(f) for f in fields))
    return hmac.compare_digest(expected, str(got))


def _amount_matches(order: Order, raw_amount) -> bool:
    try:
        return Decimal(str(raw_amount)) == Decimal(order.amount_uzs)
    except (InvalidOperation, TypeError):
        return False


def _get_order(merchant_trans_id) -> Order | None:
    if not merchant_trans_id:
        return None
    try:
        return Order.objects.get(pk=merchant_trans_id, provider=Order.Provider.CLICK)
    except (Order.DoesNotExist, ValueError, ValidationError):
        return None


def _resp(params: dict, error: int, note: str, **extra) -> dict:
    """Click javob skeleti — click_trans_id/merchant_trans_id echo + error."""
    body = {
        "click_trans_id": params.get("click_trans_id"),
        "merchant_trans_id": params.get("merchant_trans_id"),
        "error": error,
        "error_note": note,
    }
    body.update(extra)
    return body


# ── Callback handlerlari ─────────────────────────────────────────────────


def prepare(params: dict) -> dict:
    """Prepare (action=0): buyurtmani tekshiradi, click_trans_id'ni band qiladi."""
    if not check_sign(params, is_complete=False):
        return _resp(params, ERR_SIGN_CHECK, "SIGN CHECK FAILED")

    order = _get_order(params.get("merchant_trans_id"))
    if order is None:
        return _resp(params, ERR_ORDER_NOT_FOUND, "Order not found")

    if not _amount_matches(order, params.get("amount")):
        return _resp(params, ERR_INVALID_AMOUNT, "Incorrect amount")

    prepare_id = _prepare_id(order)
    click_trans_id = str(params.get("click_trans_id", ""))

    # Idempotent: shu click tranzaksiyasi allaqachon tayyorlangan -> qaytaramiz
    if order.provider_txn_id == click_trans_id and order.provider_state == STATE_PREPARED:
        return _resp(params, ERR_SUCCESS, "Success", merchant_prepare_id=prepare_id)

    if order.status == Order.Status.PAID:
        return _resp(params, ERR_ALREADY_PAID, "Already paid")
    if order.status == Order.Status.CANCELED:
        return _resp(params, ERR_CANCELLED, "Transaction cancelled")
    # CREATED bo'lishi kerak; boshqa click tranzaksiyasi band qilgan bo'lsa — xato
    if order.provider_txn_id and order.provider_txn_id != click_trans_id:
        return _resp(params, ERR_TXN_NOT_FOUND, "Another transaction in progress")

    order.provider_txn_id = click_trans_id
    order.provider_state = STATE_PREPARED
    order.provider_created_at = timezone.now()
    order.save(update_fields=["provider_txn_id", "provider_state", "provider_created_at"])
    return _resp(params, ERR_SUCCESS, "Success", merchant_prepare_id=prepare_id)


def complete(params: dict) -> dict:
    """Complete (action=1): to'lovni tasdiqlaydi -> Coin kreditlash (yoki bekor)."""
    if not check_sign(params, is_complete=True):
        return _resp(params, ERR_SIGN_CHECK, "SIGN CHECK FAILED")

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(
                pk=_safe_uuid(params.get("merchant_trans_id")),
                provider=Order.Provider.CLICK,
            )
            .first()
        )
        if order is None:
            return _resp(params, ERR_ORDER_NOT_FOUND, "Order not found")

        click_trans_id = str(params.get("click_trans_id", ""))
        # Prepare bosqichi bo'lgan bo'lishi shart (provider_txn_id mos)
        if order.provider_txn_id != click_trans_id:
            return _resp(params, ERR_TXN_NOT_FOUND, "Transaction does not exist")
        # merchant_prepare_id shu order'ga tegishli bo'lishi shart
        if str(params.get("merchant_prepare_id", "")) != str(_prepare_id(order)):
            return _resp(params, ERR_TXN_NOT_FOUND, "Prepare id mismatch")
        if not _amount_matches(order, params.get("amount")):
            return _resp(params, ERR_INVALID_AMOUNT, "Incorrect amount")

        prepare_id = _prepare_id(order)

        # Click o'z tomonidan xato/bekor yubordi (error < 0) -> buyurtmani bekor
        try:
            click_error = int(params.get("error", 0))
        except (TypeError, ValueError):
            click_error = 0
        if click_error < 0:
            order.provider_state = STATE_CANCELLED
            order.save(update_fields=["provider_state"])
            services.mark_canceled(order.id)
            return _resp(params, ERR_CANCELLED, "Transaction cancelled")

        # Idempotent: allaqachon to'langan -> muvaffaqiyat (qayta kredit YO'Q)
        if order.status == Order.Status.PAID:
            return _resp(params, ERR_SUCCESS, "Success", merchant_confirm_id=prepare_id)

        order.provider_state = STATE_CONFIRMED
        order.save(update_fields=["provider_state"])
        # Coin kreditlash — YAGONA nuqta (idempotent, ledger orqali)
        services.mark_paid(order.id)

    return _resp(params, ERR_SUCCESS, "Success", merchant_confirm_id=prepare_id)


def _safe_uuid(value):
    """UUID'ga aylantirib bo'lmaydigan qiymatda None (filter hech narsa topmaydi)."""
    import uuid

    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def checkout_url(order: Order, return_url: str = "") -> str:
    """Click to'lov sahifasi URL'i (GET redirect) [V2F-T1].

    Format: my.click.uz/services/pay?service_id=..&merchant_id=..&amount=..&
            transaction_param=<order_id>&return_url=..
    service_id/merchant_id sozlanmagan bo'lsa bo'sh string (dev fallback).
    """
    from urllib.parse import urlencode

    service_id = settings.CLICK_SERVICE_ID
    merchant_id = settings.CLICK_MERCHANT_ID
    if not service_id or not merchant_id:
        return ""
    query = {
        "service_id": service_id,
        "merchant_id": merchant_id,
        "amount": order.amount_uzs,
        "transaction_param": str(order.id),
    }
    if return_url:
        query["return_url"] = return_url
    return f"{settings.CLICK_CHECKOUT_URL}?{urlencode(query)}"
