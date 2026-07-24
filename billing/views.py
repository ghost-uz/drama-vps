"""billing/views.py — checkout boshlash + natija sahifalari [P7-T2].

Foydalanuvchi summani kiritadi -> Order (CREATED) yaratiladi -> provider
checkout sahifasiga redirect. Coin faqat webhook (to'lov tasdig'i) kelganda
qo'shiladi — bu view HECH QACHON kredit bermaydi.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from billing import services
from billing.models import Order
from billing.providers import click, payme
from core.ratelimit import rate, user_or_ip_key

# Provider -> checkout_url quruvchi (provider-agnostik dispatch [V2F-T1])
_CHECKOUT_BUILDERS = {
    Order.Provider.PAYME: payme.checkout_url,
    Order.Provider.CLICK: click.checkout_url,
}

# Minimal to'lov: kamida 1 Coin (1000 UZS) — pastida coins=0 bo'lardi
MIN_AMOUNT_UZS = 1000


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="topup", method="POST", block=True)
def checkout(request):
    """Coin sotib olishni boshlaydi (POST amount_uzs + provider payme|click)."""
    if request.method != "POST":
        return render(request, "billing/checkout.html", {"min_amount": MIN_AMOUNT_UZS})

    try:
        amount_uzs = int(request.POST.get("amount_uzs", "0"))
    except (ValueError, TypeError):
        amount_uzs = 0

    if amount_uzs < MIN_AMOUNT_UZS:
        messages.error(request, _("Eng kam summa %(amount)s UZS.") % {"amount": MIN_AMOUNT_UZS})
        return redirect("billing:checkout")

    provider = request.POST.get("provider", Order.Provider.PAYME)
    if provider not in _CHECKOUT_BUILDERS:
        provider = Order.Provider.PAYME

    order = services.create_order(request.user, provider, amount_uzs)
    url = _CHECKOUT_BUILDERS[provider](
        order, return_url=request.build_absolute_uri("/users/transactions/")
    )
    if not url:
        # Provider sozlanmagan (dev) — buyurtma qoldi, admin/qo'lda hal qiladi
        messages.warning(
            request,
            _("To'lov tizimi hozircha sozlanmagan. Iltimos, qo'lda to'ldirishdan foydalaning."),
        )
        return redirect("users:topup")
    return redirect(url)
