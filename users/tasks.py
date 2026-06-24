"""users app davriy fon vazifalari (Celery beat) [P3-T4].

Har task IDEMPOTENT: bir necha marta ishlasa ham natija bir xil (filter
faqat hali o'zgartirilmaganlarni oladi).
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def expire_premium() -> int:
    """Muddati o'tgan premiumni o'chiradi (is_premium=False)."""
    from django.utils import timezone

    from users.models import Profile

    count = Profile.objects.filter(
        is_premium=True,
        premium_until__isnull=False,
        premium_until__lt=timezone.now(),
    ).update(is_premium=False)
    if count:
        logger.info("expire_premium: %d profil premiumi tugadi", count)
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
