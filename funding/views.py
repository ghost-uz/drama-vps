from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect

from users.models import CoinTransaction
from users.services import wallet

from .models import FundingContributor, FundingProject


@login_required
def process_funding(request, project_id):
    if request.method == "POST":
        project = get_object_or_404(FundingProject, id=project_id)
        profile = request.user.profile

        if project.status == "released" and project.has_access(profile):
            messages.info(request, "Siz bu serialni allaqachon sotib olgansiz!")
            return redirect(project.movie.get_absolute_url())

        try:
            amount = int(request.POST.get("amount", 0))

            if project.status == "funding":
                if amount < project.min_fund_amount:
                    messages.error(
                        request, f"Minimal to'lov summasi {project.min_fund_amount} Coin."
                    )
                    return redirect(project.movie.get_absolute_url())
            elif project.status == "released":
                amount = project.post_release_price
            else:
                messages.warning(
                    request, "Hozircha to'lov qabul qilinmayapti (Tarjima jarayonida)."
                )
                return redirect(project.movie.get_absolute_url())

            try:
                with transaction.atomic():
                    # Ledger orqali debet — profil qatorini o'zi qulflaydi (race-safe)
                    wallet.debit(
                        profile,
                        amount,
                        CoinTransaction.Type.FUNDING,
                        description=f"{project.movie.title} loyihasiga hissa",
                        reference=f"funding:{project.id}",
                    )

                    locked_project = FundingProject.objects.select_for_update().get(id=project.id)
                    locked_project.collected_amount += amount
                    locked_project.save(update_fields=["collected_amount"])

                    FundingContributor.objects.create(
                        project=locked_project, profile=profile, amount_paid=amount
                    )
                    messages.success(
                        request,
                        f"Muvaffaqiyatli! Loyihaga {amount} Coin hissa qo'shdingiz. Rahmat!",
                    )
            except wallet.InsufficientFundsError:
                messages.error(
                    request,
                    "Hisobingizda Coin yetarli emas. Iltimos, profile bo'limidan hisobingizni to'ldiring.",
                )

        except ValueError:
            messages.error(request, "Noto'g'ri summa kiritildi.")

        return redirect(project.movie.get_absolute_url())
    return redirect("/")
