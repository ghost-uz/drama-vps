"""drama/webhooks.py — tashqi servis webhook'lari [P3-T2].

Bunny Stream encoding webhook: video tayyor bo'lganda darhol status'ni yangilaydi
(P3-T1 Celery poll'ga qo'shimcha, tezroq signal). Maxfiy URL token bilan
himoyalangan (?secret=); soxta so'rovlar 403.
"""

import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from drama.services.bunny_upload import STATUS_ERROR, STATUS_FINISHED

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def bunny_webhook(request):
    """Bunny encoding webhook — /webhooks/bunny/?secret=XXX.

    Payload: {"VideoGuid": "...", "Status": <int>}. Status -> upload_status.
    """
    secret = settings.BUNNY_WEBHOOK_SECRET
    provided = request.GET.get("secret", "")
    if not secret or not hmac.compare_digest(provided, secret):
        return JsonResponse({"detail": "forbidden"}, status=403)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "invalid json"}, status=400)

    guid = payload.get("VideoGuid")
    status_code = payload.get("Status")
    if not guid or status_code is None:
        return JsonResponse({"detail": "missing fields"}, status=400)

    from drama.models import Episode, Movie, UploadStatus

    if status_code >= STATUS_ERROR:
        new_status = UploadStatus.FAILED
    elif status_code >= STATUS_FINISHED:
        new_status = UploadStatus.READY
    else:
        new_status = UploadStatus.PROCESSING

    # GUID Episode'da ham, yakka film (Movie)da ham bo'lishi mumkin [P14-T1]
    updated = Episode.objects.filter(bunny_video_id=guid).update(upload_status=new_status)
    updated += Movie.objects.filter(bunny_video_id=guid).update(upload_status=new_status)
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
        "bunny_webhook: guid=%s status=%s -> %s (%d obyekt)", guid, status_code, new_status, updated
    )
    return JsonResponse({"ok": True, "updated": updated})
