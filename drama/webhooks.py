"""drama/webhooks.py — tashqi servis webhook'lari [P3-T2].

Bunny Stream encoding webhook: video holati o'zgarganda upload_status'ni darhol
yangilaydi (P3-T1 Celery poll'ga qo'shimcha, tezroq signal). Maxfiy URL token
bilan himoyalangan (?secret=); soxta so'rovlar 403.
"""

import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# Bunny WEBHOOK status kodlari (https://bunny.net/docs/stream/webhooks). DIQQAT:
# bu video obyektining `status` maydonidan (bunny_upload: 4=tugadi, 5/6=xato)
# FARQLI sanoq! 2026-11-18 gacha xarita video-kodlari bilan yozilgan edi:
# 3=Finished "Qayta ishlanmoqda"ga, 6/7 (presigned upload) va AI-hodisalar (9+)
# "Xato"ga tushardi.
#   0 Queued, 1 Processing, 2 Encoding, 3 Finished, 4 Resolution finished,
#   5 Failed, 6/7/8 PresignedUpload Started/Finished/Failed,
#   9-13 Captions/Title/CaptionFailed/Chapters/Moments (AI), 32 VideoDeleted,
#   33 SmartGenerationFailed
WEBHOOK_READY = frozenset({3, 4})  # 4 = birinchi sifat tayyor -> ijro mumkin
WEBHOOK_FAILED = frozenset({5, 8, 32})  # 32: video Bunny'dan o'chirilgan
WEBHOOK_PROCESSING = frozenset({0, 1, 2, 7})
WEBHOOK_UPLOADING = frozenset({6})
# Qolganlari (9-13, 33 va kelajakdagi yangi kodlar) upload holatiga aloqasiz —
# holat O'ZGARMAYDI (ilgari "Xato"ga tushirardi).


def upload_status_for(code: int):
    """Webhook kodi -> UploadStatus; informatsion/noma'lum kod uchun None."""
    from drama.models import UploadStatus

    if code in WEBHOOK_READY:
        return UploadStatus.READY
    if code in WEBHOOK_FAILED:
        return UploadStatus.FAILED
    if code in WEBHOOK_PROCESSING:
        return UploadStatus.PROCESSING
    if code in WEBHOOK_UPLOADING:
        return UploadStatus.UPLOADING
    return None


@csrf_exempt
@require_POST
def bunny_webhook(request):
    """Bunny encoding webhook — /webhooks/bunny/?secret=XXX.

    Payload: {"VideoLibraryId": .., "VideoGuid": "...", "Status": <int>, ...}.
    Status (WEBHOOK kodi, yuqoridagi jadval) -> upload_status.
    """
    secret = settings.BUNNY_WEBHOOK_SECRET
    provided = request.GET.get("secret", "")
    if not secret or not hmac.compare_digest(provided, secret):
        return JsonResponse({"detail": "forbidden"}, status=403)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "invalid json"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "invalid json"}, status=400)

    guid = payload.get("VideoGuid")
    try:
        code = int(payload.get("Status"))
    except (TypeError, ValueError):
        code = None
    if not guid or code is None:
        return JsonResponse({"detail": "missing fields"}, status=400)

    from drama.models import Episode, Movie, UploadStatus

    new_status = upload_status_for(code)
    if new_status is None:
        logger.info("bunny_webhook: guid=%s status=%s -> e'tiborsiz (informatsion)", guid, code)
        return JsonResponse({"ok": True, "updated": 0, "ignored": True})

    def pending(model):
        # Faqat HAQIQIY o'tishlar: holati allaqachon shu bo'lganlar sanalmaydi —
        # takroriy "4" (har sifat uchun) va poll'dan keyingi "3" kesh-bump /
        # xabarnomani qayta ishga tushirmaydi.
        qs = model.objects.filter(bunny_video_id=guid).exclude(upload_status=new_status)
        if new_status in (UploadStatus.PROCESSING, UploadStatus.UPLOADING):
            # Yetkazish tartibi kafolatlanmagan (Bunny docs): kechikkan
            # "Encoding" tayyor videoni qayta "Qayta ishlanmoqda"ga tushirmasin.
            qs = qs.exclude(upload_status=UploadStatus.READY)
        return qs

    # GUID Episode'da ham, yakka film (Movie)da ham bo'lishi mumkin [P14-T1]
    updated = pending(Episode).update(upload_status=new_status)
    updated += pending(Movie).update(upload_status=new_status)
    if updated and new_status == UploadStatus.READY:
        # Yangi kontent tayyor -> katalog keshini yangilaymiz.
        # .update() signal chaqirmaydi -> qo'lda bump [P9-T1]
        from drama.cache import bump_catalog_version

        bump_catalog_version()

        # Obunachilarga yangi-qism xabari [V2A-T1] — task idempotent
        # (followers_notified_at), shu sabab poll bilan poyga xavfsiz.
        from functools import partial

        from django.db import transaction

        from drama.tasks import notify_new_episode_followers

        for ep_id in Episode.objects.filter(bunny_video_id=guid).values_list("pk", flat=True):
            transaction.on_commit(partial(notify_new_episode_followers.delay, ep_id))
    logger.info(
        "bunny_webhook: guid=%s status=%s -> %s (%d obyekt)", guid, code, new_status, updated
    )
    return JsonResponse({"ok": True, "updated": updated})
