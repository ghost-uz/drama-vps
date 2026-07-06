"""users app davriy fon vazifalari (Celery beat) [P3-T4].

Har task IDEMPOTENT: bir necha marta ishlasa ham natija bir xil (filter
faqat hali o'zgartirilmaganlarni oladi).
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def expire_premium() -> int:
    """Muddati o'tgan obunalarni yopadi/uzaytiradi + legacy premiumni o'chiradi [P7-T1].

    1) ACTIVE obuna end_at < now: auto_renew bo'lsa balansdan uzaytiradi,
       aks holda EXPIRED (profil keshi ham sinxronlanadi).
    2) Legacy (obunasiz, admin qo'lda bergan) premium_until o'tganlar —
       eski xatti-harakat saqlanadi: is_premium=False.
    """
    from django.utils import timezone

    from users.models import Profile, Subscription
    from users.services import subscriptions

    now = timezone.now()
    count = 0
    stale = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE, end_at__isnull=False, end_at__lt=now
    ).select_related("profile", "plan")
    renewed = expired = 0
    for sub in stale:
        result = subscriptions.close_or_renew(sub)
        renewed += result == "renewed"
        expired += result == "expired"
    count = renewed + expired

    legacy = Profile.objects.filter(
        is_premium=True,
        premium_until__isnull=False,
        premium_until__lt=now,
    ).exclude(subscriptions__status=Subscription.Status.ACTIVE)
    legacy_count = legacy.update(is_premium=False)
    count += legacy_count

    if count:
        logger.info(
            "expire_premium: %d uzaytirildi, %d yopildi, %d legacy o'chirildi",
            renewed,
            expired,
            legacy_count,
        )
    return count


@shared_task
def cleanup_stale_topups(days: int = 7) -> int:
    """N kundan eski 'pending' topuplarni 'rejected' qiladi (audit qoladi).

    `.update()` bulk -> .save() chaqirmaydi; pending hech qachon credit
    qilinmagani uchun ledger'ga ta'sir yo'q.
    """
    from datetime import timedelta

    from django.utils import timezone

    from users.models import CryptoTopUpRequest, TopUpRequest

    cutoff = timezone.now() - timedelta(days=days)
    n1 = TopUpRequest.objects.filter(status="pending", created_at__lt=cutoff).update(
        status="rejected"
    )
    n2 = CryptoTopUpRequest.objects.filter(status="pending", created_at__lt=cutoff).update(
        status="rejected"
    )
    total = n1 + n2
    if total:
        logger.info("cleanup_stale_topups: %d eski pending -> rejected", total)
    return total
