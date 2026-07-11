"""funding/services.py — crowdfunding oqimining YAGONA kirish nuqtasi [P7-T4].

Nega servis: hissa (Coin debet + collected + access) va bekor qilish (ommaviy
refund) — pul harakatlari; view'larda sochilsa atomiklik/idempotentlik
kafolatini har chaqiruvchi o'zi qayta qurishi kerak bo'lardi. Bu modul:

* hissani BITTA tranzaksiyada, loyiha qatorini qulflab o'tkazadi — parallel
  hissa/bekor-qilish poygasi xavfsiz (qulf tartibi ikkala yo'lda ham bir xil:
  loyiha -> profil);
* maqsadga yetganda statusni o'zi TRANSLATING'ga o'tkazadi va hissadorlarga
  xabar beradi;
* released loyihada qayta sotib olishni QULF ICHIDA tekshiradi (double-charge
  himoyasi — ilgari view'da qulfsiz tekshirilardi);
* bekor qilishda barcha faol hissani qaytaradi — refunded_at belgisi bilan
  IDEMPOTENT (takror chaqiruv ikkinchi marta pul bermaydi).

Coin harakati faqat users/services/wallet.py orqali (P1-T4 invarianti).
"""

from __future__ import annotations

from functools import partial

from django.db import transaction
from django.utils import timezone

from core.tasks import notify_telegram_task
from funding.models import FundingContributor, FundingProject
from users.models import CoinTransaction, Notification
from users.services import notifications, wallet


class FundingError(Exception):
    """Funding oqimidagi, foydalanuvchiga ko'rsatsa bo'ladigan xato (bazaviy)."""


class NotAcceptingContributions(FundingError):
    """Loyiha holati to'lov qabul qilmaydi (translating/canceled)."""


class BelowMinimum(FundingError):
    """Hissa min_fund_amount'dan kichik."""


class AlreadyPurchased(FundingError):
    """Released loyiha allaqachon sotib olingan."""


def contribute(profile, project_id: int, amount: int) -> FundingContributor:
    """Loyihaga hissa qo'shadi (released bo'lsa — sotib oladi). To'liq atomik.

    Qaytaradi: yaratilgan FundingContributor (``amount_paid`` — haqiqiy summa:
    released holatda foydalanuvchi kiritgani emas, ``post_release_price``).

    Raises:
        AlreadyPurchased: released loyiha allaqachon olingan.
        BelowMinimum: funding holatida hissa minimaldan kichik.
        NotAcceptingContributions: translating/canceled holat.
        wallet.InsufficientFundsError: balans yetarli emas (hech narsa yozilmaydi).
    """
    with transaction.atomic():
        project = (
            FundingProject.objects.select_for_update().select_related("movie").get(pk=project_id)
        )

        if project.status == FundingProject.Status.RELEASED:
            # Qayta sotib olish tekshiruvi QULF ICHIDA — parallel ikki so'rovning
            # ikkalasi ham o'tib ketishi (double-charge) mumkin emas.
            if project.has_access(profile):
                raise AlreadyPurchased("Siz bu serialni allaqachon sotib olgansiz!")
            amount = project.post_release_price
        elif project.status == FundingProject.Status.FUNDING:
            if amount < project.min_fund_amount:
                raise BelowMinimum(f"Minimal to'lov summasi {project.min_fund_amount} Coin.")
        elif project.status == FundingProject.Status.CANCELED:
            raise NotAcceptingContributions("Bu loyiha bekor qilingan — to'lov qabul qilinmaydi.")
        else:  # TRANSLATING
            raise NotAcceptingContributions(
                "Hozircha to'lov qabul qilinmayapti (Tarjima jarayonida)."
            )

        # Ledger orqali debet — profil qatorini o'zi qulflaydi (race-safe)
        wallet.debit(
            profile,
            amount,
            CoinTransaction.Type.FUNDING,
            description=f"{project.movie.title} loyihasiga hissa",
            reference=f"funding:{project.pk}",
        )

        project.collected_amount += amount
        goal_reached = (
            project.status == FundingProject.Status.FUNDING
            and project.collected_amount >= project.target_amount
        )
        if goal_reached:
            project.status = FundingProject.Status.TRANSLATING
            project.save(update_fields=["collected_amount", "status"])
        else:
            project.save(update_fields=["collected_amount"])

        contribution = FundingContributor.objects.create(
            project=project, profile=profile, amount_paid=amount
        )

        _notify_admin_contribution(project, profile, amount, goal_reached=goal_reached)
        if goal_reached:
            _notify_goal_reached(project)

    return contribution


def cancel_project(project_id: int) -> int:
    """Loyihani bekor qiladi va barcha faol (qaytarilmagan) hissani refund qiladi.

    IDEMPOTENT: har hissa ``refunded_at`` bilan belgilanadi — takror chaqiruv
    0 qaytaradi va hech kimga ikkinchi marta pul bermaydi. Refund kreditlari
    ledger'da ``Type.REFUND`` + ``funding-refund:<loyiha>:<hissa>`` reference
    bilan yoziladi (audit iziga qarab har kreditning manbai topiladi).

    Qaytaradi: shu chaqiruvda refund qilingan hissalar soni.

    Raises:
        FundingError: released loyihani bekor qilib bo'lmaydi (kontent chiqqan,
            hissadorlar accessidan foydalanmoqda).
    """
    now = timezone.now()
    with transaction.atomic():
        project = (
            FundingProject.objects.select_for_update().select_related("movie").get(pk=project_id)
        )
        if project.status == FundingProject.Status.RELEASED:
            raise FundingError("Chiqarilgan (released) loyihani bekor qilib bo'lmaydi.")

        pending = list(
            project.contributors.filter(refunded_at__isnull=True).select_related("profile__user")
        )
        for contribution in pending:
            if contribution.amount_paid > 0:
                wallet.credit(
                    contribution.profile,
                    contribution.amount_paid,
                    CoinTransaction.Type.REFUND,
                    description=f"{project.movie.title} loyihasi bekor qilindi — hissa qaytarildi",
                    reference=f"funding-refund:{project.pk}:{contribution.pk}",
                )
            contribution.refunded_at = now
            contribution.save(update_fields=["refunded_at"])

        if project.status != FundingProject.Status.CANCELED:
            project.status = FundingProject.Status.CANCELED
            project.save(update_fields=["status"])

        if pending:
            notifications.notify_bulk(
                [c.profile.user_id for c in pending],
                Notification.Kind.FUNDING,
                "Loyiha bekor qilindi — hissangiz qaytarildi",
                body=(
                    f"{project.movie.title} tarjima loyihasi bekor qilindi; "
                    "Coin'laringiz balansingizga qaytarildi."
                ),
                url=project.movie.get_absolute_url(),
            )

    return len(pending)


def _notify_admin_contribution(project, profile, amount, *, goal_reached: bool) -> None:
    """Yangi hissa -> admin Telegram (maqsadga yetsa qo'shimcha belgi) [P3-T3]."""
    msg = (
        f"💰 <b>YANGI FUNDING HISSASI</b>\n\n"
        f"🎬 <b>Loyiha:</b> {project.movie.title}\n"
        f"👤 <b>Hissador:</b> @{profile.user.username}\n"
        f"🪙 <b>Hissa:</b> {amount} Coin\n"
        f"📊 <b>Yig'ildi:</b> {project.collected_amount}/{project.target_amount} Coin"
    )
    if goal_reached:
        msg += "\n\n🎉 <b>MAQSADGA YETILDI!</b> Holat: Tarjima jarayonida"
    transaction.on_commit(partial(notify_telegram_task.delay, msg))


def _notify_goal_reached(project) -> None:
    """Maqsadga yetdi — barcha faol hissadorlarga sayt-ichi bildirishnoma."""
    user_ids = (
        FundingContributor.objects.filter(project=project, refunded_at__isnull=True)
        .values_list("profile__user_id", flat=True)
        .distinct()
    )
    notifications.notify_bulk(
        user_ids,
        Notification.Kind.FUNDING,
        "🎉 Loyiha maqsadga yetdi!",
        body=f"{project.movie.title} — mablag' to'liq yig'ildi, tarjima boshlanadi.",
        url=project.movie.get_absolute_url(),
    )
