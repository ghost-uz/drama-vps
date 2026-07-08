import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from core.ratelimit import ip_key, rate, user_or_ip_key
from core.tasks import notify_telegram_task
from users.utils import follow, unfollow

from .forms import (
    CryptoTopUpRequestForm,
    ProfileUpdateForm,
    TopUpRequestForm,
    UserRegisterForm,
    UserUpdateForm,
)
from .models import (
    CoinTransaction,
    CryptoTopUpRequest,
    Notification,
    SubscriptionPlan,
    TopUpRequest,
    UserMovieList,
)
from .selectors import continue_watching
from .services import email_verification, notifications, subscriptions, telegram_auth, wallet

logger = logging.getLogger(__name__)

# Telegram bildirishnoma core/notifications.py + core/tasks.py'ga ko'chirildi [P3-T3];
# view'lar notify_telegram_task.delay(...) ishlatadi (async — request bloklanmaydi).


@ratelimit(key=ip_key, rate=rate, group="register", method="POST", block=True)
def register(request):
    if request.user.is_authenticated:
        # FIX: 'drama:home' mavjud emas → to'g'ri name 'drama:movie_list'
        return redirect("drama:movie_list")

    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    # Tasdiqlash havolasi — on_commit'da fon (Celery)ga ketadi [P6-T1]
                    email_verification.send_verification_email(user, request)
                username = form.cleaned_data.get("username")
                messages.success(
                    request,
                    f"Xush kelibsiz {username}! Account yaratildi. "
                    f"Emailingizga tasdiqlash havolasi yubordik (spam papkasini ham "
                    f"tekshiring). Endi username va parolingiz bilan kiring.",
                )
                return redirect("users:login")
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {e}")
    else:
        form = UserRegisterForm()

    return render(request, "users/register.html", {"form": form})


def verify_email(request, key):
    """Emaildagi tasdiqlash havolasi [P6-T1]. Login talab qilinmaydi —
    imzolangan kalitning o'zi yetarli (havola boshqa qurilmada ochilishi mumkin)."""
    email_address = email_verification.confirm_key(key)
    if email_address is None:
        messages.error(request, "Tasdiqlash havolasi yaroqsiz yoki muddati o'tgan.")
    else:
        messages.success(request, f"{email_address.email} manzili tasdiqlandi ✅")
    if request.user.is_authenticated:
        return redirect("users:settings")
    return redirect("users:login")


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="resend_verify", method="POST", block=True)
def resend_verification(request):
    """Tasdiqlash havolasini qayta yuborish [P6-T1] (settings sahifasidagi tugma)."""
    if request.method != "POST":
        return redirect("users:settings")

    if not request.user.email:
        messages.error(request, "Avval sozlamalarda email manzil kiriting.")
    elif email_verification.is_verified(request.user):
        messages.info(request, "Emailingiz allaqachon tasdiqlangan.")
    else:
        email_verification.send_verification_email(request.user, request)
        messages.success(request, "Tasdiqlash havolasi qayta yuborildi.")
    return redirect("users:settings")


_MODELBACKEND = "django.contrib.auth.backends.ModelBackend"


def _safe_next(request, fallback="drama:movie_list"):
    """?next= ochiq-redirectdan xavfsiz bo'lsa qaytaradi, aks holda fallback."""
    nxt = request.GET.get("next") or request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return reverse(fallback)


@csrf_exempt
@ratelimit(key=ip_key, rate=rate, group="telegram_login", method=["GET", "POST"], block=True)
def telegram_login(request):
    """Telegram orqali kirish [P6-T2].

    GET  — Login Widget (data-auth-url) imzolangan query params bilan yo'naltiradi.
    POST — Mini App: `init_data` (initData query-string) form yoki JSON bilan.

    HMAC imzo autentifikatsiya vazifasini bajaradi (bot token'siz soxtalab bo'lmaydi)
    → csrf_exempt (widget cross-site GET; Mini App fetch). Yaroqli bo'lsa hisob
    topiladi/yaratiladi/bog'lanadi va login qilinadi.
    """
    bot_token = settings.TELEGRAM_LOGIN_BOT_TOKEN
    max_age = settings.TELEGRAM_LOGIN_MAX_AGE
    current = request.user if request.user.is_authenticated else None

    if request.method == "POST":
        init_data = request.POST.get("init_data", "")
        if not init_data and request.content_type == "application/json":
            try:
                init_data = json.loads(request.body or b"{}").get("init_data", "")
            except (ValueError, TypeError):
                init_data = ""
        tg = telegram_auth.verify_webapp_init_data(init_data, bot_token=bot_token, max_age=max_age)
        if tg is None:
            return JsonResponse({"ok": False, "detail": "Telegram imzosi yaroqsiz."}, status=403)
        user, _ = telegram_auth.get_or_create_user(tg, current_user=current)
        auth_login(request, user, backend=_MODELBACKEND)
        return JsonResponse({"ok": True, "redirect": _safe_next(request)})

    tg = telegram_auth.verify_login_widget(request.GET.dict(), bot_token=bot_token, max_age=max_age)
    if tg is None:
        messages.error(request, "Telegram orqali kirishda xatolik (imzo yaroqsiz yoki eskirgan).")
        return redirect("users:login")
    user, _created = telegram_auth.get_or_create_user(tg, current_user=current)
    auth_login(request, user, backend=_MODELBACKEND)
    messages.success(request, f"Xush kelibsiz, {user.username}! Telegram orqali kirdingiz.")
    return redirect(_safe_next(request))


def profile_view(request, username):
    person = get_object_or_404(User, username=username)
    profile = person.profile

    watched_history = UserMovieList.objects.filter(profile=profile).select_related("movie")[:5]

    # Review modeli user FK ga related_name yo'q, shuning uchun review_set ishlatamiz
    stats = {
        "watched_count": UserMovieList.objects.filter(profile=profile, status=2).count(),
        "list_count": profile.movie_list.count(),
        "review_count": person.review_set.count(),
        "followers_count": profile.followers.count(),
        "following_count": profile.following.count(),
    }

    # Follow holatini tekshirish — .exists() bilan, barcha followerlarni yuklamasdan
    is_following = False
    if request.user.is_authenticated and request.user != person:
        is_following = request.user.profile.following.filter(pk=profile.pk).exists()

    context = {
        "person": person,
        "profile": profile,
        "watched_history": watched_history,
        "is_following": is_following,
        # 'Davom ettirish' — faqat o'z profilida (shaxsiy progress) [P6-T3]
        "continue_watching": continue_watching(person, limit=6) if request.user == person else None,
        **stats,
    }
    return render(request, "users/profile.html", context)


# FIX: Follow/Unfollow — faqat POST so'rov qabul qiladi (CSRF himoyasi)
@login_required
def follow_user(request, username):
    if request.method != "POST":
        return redirect("users:profile", username=username)

    target_user = get_object_or_404(User, username=username)

    # O'zini follow qilishning oldini olish
    if request.user != target_user:
        # Takroriy follow POST'da bildirishnoma dublikatlanmasligi uchun avval tekshiramiz
        already = request.user.profile.following.filter(pk=target_user.profile.pk).exists()
        follow(request.user, target_user)
        if not already:
            notifications.notify(
                target_user,
                Notification.Kind.FOLLOW,
                "Yangi obunachi",
                body=f"{request.user.username} sizni kuzatmoqda.",
                url=reverse("users:profile", args=[request.user.username]),
            )

    return redirect("users:profile", username=username)


@login_required
def unfollow_user(request, username):
    if request.method != "POST":
        return redirect("users:profile", username=username)

    target_user = get_object_or_404(User, username=username)

    if request.user != target_user:
        unfollow(request.user, target_user)

    return redirect("users:profile", username=username)


def followers_view(request, username):
    person = get_object_or_404(User, username=username)
    # followers → Profile objectlar (symmetrical=False, related_name='followers')
    followers = person.profile.followers.all().select_related("user")

    return render(
        request,
        "users/followers.html",
        {
            "person": person,
            "followers": followers,
        },
    )


def following_view(request, username):
    person = get_object_or_404(User, username=username)
    following = person.profile.following.all().select_related("user")

    return render(
        request,
        "users/following.html",
        {
            "person": person,
            "following": following,
        },
    )


def user_full_list(request, username):
    target_user = get_object_or_404(User, username=username)

    user_items = (
        UserMovieList.objects.filter(profile=target_user.profile)
        .select_related("movie")
        .order_by("-updated_at")
    )

    is_owner = request.user == target_user
    page_title = "Mening ro'yxatim" if is_owner else f"{target_user.username}ning ro'yxati"

    context = {
        "target_user": target_user,
        "is_owner": is_owner,
        "title": page_title,
        "watching": user_items.filter(status=1),
        "completed": user_items.filter(status=2),
        "plan_to_watch": user_items.filter(status=3),
        "on_hold": user_items.filter(status=4),
        "dropped": user_items.filter(status=5),
        "total_count": user_items.count(),
    }

    return render(request, "users/my_full_list.html", context)


@login_required
def settings_view(request):
    # DIQQAT: ModelForm is_valid() instance'ni mutatsiya qiladi (_post_clean) —
    # eski email va tasdiq holatini forma yaratilishidan OLDIN olamiz [P6-T1].
    old_email = request.user.email
    email_verified = email_verification.is_verified(request.user)

    if request.method == "POST":
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            with transaction.atomic():
                u_form.save()
                p_form.save()
            messages.success(request, "Ma'lumotlaringiz muvaffaqiyatli yangilandi!")
            # Email o'zgardi -> yangi manzil tasdiqlanmagan, havola yuboramiz [P6-T1]
            if (request.user.email or "").lower() != (old_email or "").lower():
                email_verification.send_verification_email(request.user, request)
                messages.info(request, "Yangi emailingizga tasdiqlash havolasi yubordik.")
            return redirect("users:settings")
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile)

    return render(
        request,
        "users/settings.html",
        {
            "u_form": u_form,
            "p_form": p_form,
            "email_verified": email_verified,
            "title": "Profil sozlamalari",
        },
    )


def subscription_view(request):
    """Obuna sahifasi — rejalar DB'dan (admin boshqaradi) [P7-T1]."""
    plans = SubscriptionPlan.objects.filter(is_active=True)
    current_sub = None
    if request.user.is_authenticated:
        current_sub = subscriptions.active_subscription(request.user.profile)
    return render(
        request,
        "pages/subscription.html",
        {
            "plans": plans,
            "current_sub": current_sub,
            "title": "VIP Obuna - Premium imkoniyatlar",
        },
    )


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="premium", method="POST", block=True)
def buy_premium(request):
    """Reja-asosli obuna xaridi [P7-T1] — mantiq services/subscriptions.py da.

    POST'da `plan` (pk) ixtiyoriy: berilmasa birinchi aktiv reja (eski
    bir-tugmali forma bilan moslik saqlanadi).
    """
    if request.method == "POST":
        plan_id = request.POST.get("plan")
        plans = SubscriptionPlan.objects.filter(is_active=True)
        plan = plans.filter(pk=plan_id).first() if plan_id else plans.first()

        if plan is None:
            messages.error(request, "Obuna rejasi topilmadi yoki sotuvda emas.")
            return redirect("users:subscription")

        try:
            subscriptions.purchase(
                request.user.profile,
                plan,
                auto_renew=request.POST.get("auto_renew") == "on",
            )
            messages.success(
                request, f"Tabriklaymiz! {plan.name} obunasi muvaffaqiyatli xarid qilindi 👑"
            )
        except wallet.InsufficientFundsError:
            messages.error(
                request, f"Hisobingizda mablag' yetarli emas! Narxi: {plan.price_coins} Coin."
            )
        except subscriptions.LifetimeSubscriptionError:
            messages.info(request, "Sizda muddatsiz VIP mavjud — xarid shart emas.")

    return redirect("users:profile", username=request.user.username)


@login_required
def toggle_auto_renew(request):
    """Aktiv obunada avto-uzaytirishni yoqish/o'chirish [P7-T1]."""
    if request.method != "POST":
        return redirect("users:subscription")

    sub = subscriptions.active_subscription(request.user.profile)
    if sub is None:
        messages.error(request, "Sizda aktiv obuna yo'q.")
    else:
        sub.auto_renew = not sub.auto_renew
        sub.save(update_fields=["auto_renew", "updated_at"])
        holat = "yoqildi" if sub.auto_renew else "o'chirildi"
        messages.success(request, f"Avto-uzaytirish {holat}.")
    return redirect("users:subscription")


@login_required
def transactions_view(request):
    """Foydalanuvchining coin tranzaksiyalari tarixi (ledger)."""
    qs = CoinTransaction.objects.filter(profile=request.user.profile)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "users/transactions.html",
        {
            "page_obj": page_obj,
            "profile": request.user.profile,
            "title": "Tranzaksiyalar tarixi",
        },
    )


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="topup", method="POST", block=True)
def topup_view(request):
    pending_request = TopUpRequest.objects.filter(user=request.user, status="pending").first()

    if request.method == "POST":
        if pending_request:
            messages.error(request, "Sizda allaqachon kutilayotgan so'rov mavjud!")
            return redirect("users:topup")

        form = TopUpRequestForm(request.POST, request.FILES)
        if form.is_valid():
            topup = form.save(commit=False)
            topup.user = request.user
            topup.save()

            msg = (
                f"🚨 <b>YANGI TO'LOV SO'ROVI!</b>\n\n"
                f"👤 <b>Foydalanuvchi:</b> @{request.user.username}\n"
                f"💵 <b>To'lov summasi:</b> {topup.amount_uzs} UZS\n"
                f"💎 <b>Beriladigan Coin:</b> {topup.points} Coin\n\n"
                f"👉 https://drama.uz/admin/users/topuprequest/"
            )
            notify_telegram_task.delay(msg)

            messages.success(
                request, "So'rovingiz muvaffaqiyatli yuborildi! Admin tasdiqlashini kuting."
            )
            return redirect("users:topup")
    else:
        form = TopUpRequestForm()

    return render(
        request,
        "users/topup.html",
        {
            "form": form,
            "pending_request": pending_request,
            "title": "Hisobni to'ldirish",
        },
    )


@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="topup", method="POST", block=True)
def crypto_topup_view(request):
    pending_request = CryptoTopUpRequest.objects.filter(user=request.user, status="pending").first()

    if request.method == "POST":
        if pending_request:
            messages.error(request, "Sizda allaqachon kutilayotgan kripto so'rov mavjud!")
            return redirect("users:crypto_topup")

        form = CryptoTopUpRequestForm(request.POST, request.FILES)
        if form.is_valid():
            topup = form.save(commit=False)
            topup.user = request.user
            topup.save()

            msg = (
                f"💎 <b>YANGI KRIPTO TO'LOV SO'ROVI!</b>\n\n"
                f"👤 <b>Foydalanuvchi:</b> @{request.user.username}\n"
                f"💵 <b>To'lov summasi:</b> {topup.amount_usdt} USDT (TON)\n"
                f"🪙 <b>Beriladigan Coin:</b> {topup.points} Coin\n\n"
                f"👉 https://drama.uz/admin/users/cryptotopuprequest/"
            )
            notify_telegram_task.delay(msg)

            messages.success(
                request, "So'rovingiz muvaffaqiyatli yuborildi! Admin tasdiqlashini kuting."
            )
            return redirect("users:crypto_topup")
    else:
        form = CryptoTopUpRequestForm()

    return render(
        request,
        "users/topup_crypto.html",
        {
            "form": form,
            "pending_request": pending_request,
            "title": "Kripto orqali to'ldirish",
        },
    )


@login_required
def notifications_view(request):
    """Bildirishnomalar markazi [P6-T3] — foydalanuvchining o'z ro'yxati (paginatsiyalangan)."""
    qs = Notification.objects.filter(recipient=request.user)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "users/notifications.html",
        {"page_obj": page_obj, "title": "Bildirishnomalar"},
    )


@login_required
def mark_notification_read(request, pk):
    """Bitta bildirishnomani o'qilgan qilib, havolasiga yo'naltiradi (POST) [P6-T3]."""
    if request.method != "POST":
        return redirect("users:notifications")
    # IDOR himoyasi: faqat o'z bildirishnomasi (recipient bo'yicha filtr)
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return redirect(notification.url or "users:notifications")


@login_required
def mark_all_notifications_read(request):
    """Barcha o'qilmaganlarni o'qilgan qiladi (POST) [P6-T3]."""
    if request.method != "POST":
        return redirect("users:notifications")
    notifications.mark_all_read(request.user)
    messages.success(request, "Barcha bildirishnomalar o'qilgan deb belgilandi.")
    return redirect("users:notifications")
