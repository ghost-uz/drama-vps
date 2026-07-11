"""core/twofactor.py — admin 2FA (TOTP) tasdiqlash sahifasi [P10-T4].

Nega OTPAdminSite emas: u admin LOGIN formasini almashtiradi — unfold'ning
login shablonida otp_token maydoni renderlanishiga kafolat yo'q (jimgina
sindirish xavfi, P10-T1 admin-eval saboqi). Alohida sahifa: mavjud login
oqimi o'zgarmaydi; parol tekshiruvidan o'tgan staff shu yerda token kiritadi.
Yo'naltirishni config.middleware.AdminTwoFactorMiddleware bajaradi.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django_otp import login as otp_login
from django_otp import user_has_device
from django_otp.forms import OTPTokenForm
from django_ratelimit.decorators import ratelimit

from core.ratelimit import rate, user_or_ip_key


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="otp_verify", method="POST", block=True)
def admin_2fa_verify(request):
    if not request.user.is_staff:
        return redirect("/")
    if request.user.is_verified():
        return redirect("admin:index")

    has_device = user_has_device(request.user, confirmed=True)
    form = None
    if has_device:
        form = OTPTokenForm(request.user, request, request.POST or None)
        if request.method == "POST" and form.is_valid():
            # clean_otp muvaffaqiyatda device'ni user.otp_device'ga bog'laydi;
            # otp_login sessiyani "verified" qiladi — middleware endi o'tkazadi
            otp_login(request, request.user.otp_device)
            return redirect("admin:index")
    return render(request, "admin_2fa_verify.html", {"form": form, "has_device": has_device})
