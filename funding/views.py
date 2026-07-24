"""funding/views.py — HTTP qatlam, xolos: parse -> services.contribute -> message.

Biznes-oqim (gulf, ledger, goal-transition, xabarlar) funding/services.py'da
[P7-T4] — API yoki boshqa kirish nuqtasi qo'shilsa shu servisni chaqiradi.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from core.ratelimit import rate, user_or_ip_key
from users.services import wallet

from . import services
from .models import FundingProject


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="funding", method="POST", block=True)
def process_funding(request, project_id):
    if request.method != "POST":
        return redirect("/")

    project = get_object_or_404(FundingProject.objects.select_related("movie"), id=project_id)
    redirect_url = project.movie.get_absolute_url()

    try:
        amount = int(request.POST.get("amount", 0))
    except ValueError:
        messages.error(request, _("Noto'g'ri summa kiritildi."))
        return redirect(redirect_url)

    try:
        contribution = services.contribute(request.user.profile, project.id, amount)
    except services.AlreadyPurchased as exc:
        messages.info(request, str(exc))
    except services.NotAcceptingContributions as exc:
        messages.warning(request, str(exc))
    except services.FundingError as exc:  # BelowMinimum va boshqa validatsiyalar
        messages.error(request, str(exc))
    except wallet.InsufficientFundsError:
        messages.error(
            request,
            _(
                "Hisobingizda Coin yetarli emas. Iltimos, profile bo'limidan hisobingizni to'ldiring."
            ),
        )
    else:
        messages.success(
            request,
            _("Muvaffaqiyatli! Loyihaga %(coins)s Coin hissa qo'shdingiz. Rahmat!")
            % {"coins": contribution.amount_paid},
        )
    return redirect(redirect_url)
