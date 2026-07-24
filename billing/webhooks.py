"""billing/webhooks.py — Payme JSON-RPC endpoint [P7-T2].

Payme SHU endpoint'ga chaqiradi. Har javob JSON-RPC 2.0 (HTTP 200 — xato ham
javob tanasida `error` obyekti sifatida, Payme shuni kutadi). Autentifikatsiya
HTTP Basic (payme.check_auth) — muvaffaqiyatsiz -> -32504.

CSRF yo'q (tashqi server chaqiradi); himoya = Basic-auth merchant kaliti.
"""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.providers import payme

logger = logging.getLogger(__name__)


def _error(req_id, code: int, message, data=None) -> JsonResponse:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JsonResponse({"jsonrpc": "2.0", "id": req_id, "error": error})


@csrf_exempt
@require_POST
def payme_webhook(request):
    # 1) Autentifikatsiya — merchant kaliti (Basic auth)
    if not payme.check_auth(request.headers.get("authorization")):
        return _error(
            None,
            -32504,
            {
                "ru": "Недостаточно привилегий",
                "uz": "Ruxsat yetarli emas",
                "en": "Insufficient privileges",
            },
        )

    # 2) JSON tahlili
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(
            None, -32700, {"ru": "Ошибка парсинга", "uz": "Tahlil xatosi", "en": "Parse error"}
        )

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    # 3) Metodni bajarish
    try:
        result = payme.handle(method, params)
    except payme.PaymeError as exc:
        return _error(req_id, exc.code, exc.message, exc.data)
    except Exception:  # kutilmagan xato — Payme'ga -32400 (ichki), log bilan
        logger.exception("Payme webhook ichki xatosi: method=%s", method)
        return _error(
            req_id, -32400, {"ru": "Системная ошибка", "uz": "Tizim xatosi", "en": "System error"}
        )

    return JsonResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


# ── Click Merchant API (form-encoded Prepare/Complete) [V2F-T1] ───────────
# Payme'dan farqli: JSON-RPC emas, ikkita alohida endpoint. Har biri form-POST
# oladi, javob JSON. Imzo (sign_string) tekshiruvi provider ichida — noto'g'ri
# imzo error=-1 bo'lib qaytadi (HTTP 200; Click javob tanasidagi `error`ni o'qiydi).


def _click_params(request) -> dict:
    """Click POST maydonlarini dict'ga (form-encoded yoki JSON — ikkalasiga toqat)."""
    if request.POST:
        return request.POST.dict()
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


@csrf_exempt
@require_POST
def click_prepare(request):
    from billing.providers import click

    params = _click_params(request)
    try:
        result = click.prepare(params)
    except Exception:  # noqa: BLE001 — kutilmagan xato ham Click formatida qaytsin
        logger.exception("Click prepare ichki xatosi")
        result = click._resp(params, click.ERR_BAD_REQUEST, "Internal error")
    return JsonResponse(result)


@csrf_exempt
@require_POST
def click_complete(request):
    from billing.providers import click

    params = _click_params(request)
    try:
        result = click.complete(params)
    except Exception:  # noqa: BLE001
        logger.exception("Click complete ichki xatosi")
        result = click._resp(params, click.ERR_BAD_REQUEST, "Internal error")
    return JsonResponse(result)
