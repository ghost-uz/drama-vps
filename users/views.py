import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.tasks import notify_telegram_task
from users.utils import follow, unfollow

from .forms import (
    CryptoTopUpRequestForm,
    ProfileUpdateForm,
    TopUpRequestForm,
    UserRegisterForm,
    UserUpdateForm,
)
from .models import CoinTransaction, CryptoTopUpRequest, TopUpRequest, UserMovieList
from .services import wallet

logger = logging.getLogger(__name__)

# Telegram bildirishnoma core/notifications.py + core/tasks.py'ga ko'chirildi [P3-T3];
# view'lar notify_telegram_task.delay(...) ishlatadi (async — request bloklanmaydi).


def register(request):
    if request.user.is_authenticated:
        # FIX: 'drama:home' mavjud emas → to'g'ri name 'drama:movie_list'
        return redirect("drama:movie_list")

    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                username = form.cleaned_data.get("username")
                messages.success(
                    request,
                    f"Xush kelibsiz {username}! Account yaratildi. "
                    f"Endi username va parolingiz bilan kiring.",
                )
                return redirect("users:login")
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {e}")
    else:
        form = UserRegisterForm()

    return render(request, "users/register.html", {"form": form})


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
        follow(request.user, target_user)

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
    if request.method == "POST":
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            with transaction.atomic():
                u_form.save()
                p_form.save()
            messages.success(request, "Ma'lumotlaringiz muvaffaqiyatli yangilandi!")
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
            "title": "Profil sozlamalari",
        },
    )


def subscription_view(request):
    return render(
        request,
        "pages/subscription.html",
        {
            "vip_price": 15,
            "title": "VIP Obuna - Premium imkoniyatlar",
        },
    )


@login_required
def buy_premium(request):
    if request.method == "POST":
        VIP_PRICE_1_MONTH = 15
        profile = request.user.profile

        try:
            with transaction.atomic():
                # Ledger orqali debet — balans yetmasa InsufficientFundsError
                wallet.debit(
                    profile,
                    VIP_PRICE_1_MONTH,
                    CoinTransaction.Type.VIP,
                    description="1 oylik VIP obuna",
                )

                now = timezone.now()
                if profile.is_premium and profile.premium_until:
                    if isinstance(profile.premium_until, datetime):
                        is_active = profile.premium_until > now
                    else:
                        is_active = profile.premium_until > now.date()

                    if is_active:
                        profile.premium_until += timedelta(days=30)
                    else:
                        profile.premium_until = now + timedelta(days=30)
                else:
                    profile.premium_until = now + timedelta(days=30)

                profile.is_premium = True
                # balance allaqachon wallet.debit() ichida saqlangan
                profile.save(update_fields=["is_premium", "premium_until"])

            messages.success(request, "Tabriklaymiz! VIP obuna muvaffaqiyatli xarid qilindi 👑")
        except wallet.InsufficientFundsError:
            messages.error(
                request, f"Hisobingizda mablag' yetarli emas! VIP narxi: {VIP_PRICE_1_MONTH} Coin."
            )

    return redirect("users:profile", username=request.user.username)


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
