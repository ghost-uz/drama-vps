from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta, datetime

from django.shortcuts import render, redirect
from .models import Profile
from users.utils import get_user_by_username, follow, unfollow

from .forms import UserRegisterForm, UserUpdateForm, ProfileUpdateForm, TopUpRequestForm
from .models import UserMovieList, TopUpRequest

# Telegramga yangi VIP xaridi haqida xabar yuboramiz
import requests
import logging

logger = logging.getLogger(__name__)

def send_telegram_notification(message):
    """Telegram bot orqali adminga xabar yuboruvchi yordamchi funksiya"""
    # SHU YERGA O'ZINGIZNING TOKEN VA ID RAQAMINGIZNI YOZING
    BOT_TOKEN = '8747095936:AAE2wZukxrdOZlSsmYG4RRqq7PEhyyR0dBE' 
    ADMIN_CHAT_ID = '1823516763' 
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': ADMIN_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    try:
        # timeout=3 qo'yganimiz sababi, agar telegram serveri qotib qolsa saytimiz kutib qolmasligi kerak
        requests.post(url, data=payload, timeout=3)
    except Exception as e:
        logger.error(f"Telegramga xabar yuborishda xatolik: {e}")
# Telegramga yangi VIP xaridi haqida xabar yuboramiz


def profile_detail(request, username, action=None):
    person = get_user_by_username(username)
    profile = person.profile
    watched_count = person.watched_movies.count()

    if request.user == person:
        # Follow/Unfollow logic here
        if action == 'follow' and not person.followers.filter(pk=request.user.pk).exists():
            person.followers.add(request.user)
        elif action == 'unfollow':
            person.followers.remove(request.user)

    return render(request, 'users/profile.html', {
        'person': person,
        'profile': profile,
        'watched_count': watched_count,
    })

def register(request):
    if request.user.is_authenticated:
        return redirect('drama:home')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                username = form.cleaned_data.get('username')
                messages.success(request, f"Xush kelibsiz {username}! Siz uchun {username} nomli account yaratildi. Endi siz login sahifasiga o'tib username va parolingnizni yozib accountingizga kirishingiz mumkin!")
                return redirect('users:login')
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {e}")
    else:
        form = UserRegisterForm()
    
    return render(request, 'users/register.html', {'form': form})


def profile_view(request, username):
    person = get_object_or_404(User, username=username)
    profile = person.profile
    
    watched_history = UserMovieList.objects.filter(profile=profile).select_related('movie')[:5]
    watched_count = UserMovieList.objects.filter(profile=profile, status=2).count()
    
    context = {
        'person': person,
        'profile': profile,
        'watched_history': watched_history,
        'watched_count': watched_count,
    }
    return render(request, 'users/profile.html', context)

#test
@login_required
def follow_user(request, username):
    # ✅ get_object_or_404 ishlatamiz, xavfsizroq
    target_user = get_object_or_404(User, username=username)
    
    # ✅ O'zini follow qilishning oldini olamiz
    if request.user != target_user:
        follow(request.user, target_user)
    
    return redirect('users:profile', username=username)

@login_required
def unfollow_user(request, username):
    target_user = get_object_or_404(User, username=username)
    
    if request.user != target_user:
        unfollow(request.user, target_user)
    
    return redirect('users:profile', username=username)


def followers_view(request, username):
    # ✅ get_object_or_404 ishlatamiz
    person = get_object_or_404(User, username=username)
    followers = person.profile.followers.all()  # Profile objectlar qaytadi
    
    return render(request, 'users/followers.html', {
        'person': person,
        'followers': followers,  # ✅ 'person' ham uzatamiz (template uchun)
    })

def following_view(request, username):
    person = get_object_or_404(User, username=username)
    following = person.profile.following.all()  # Profile objectlar qaytadi
    
    return render(request, 'users/following.html', {
        'person': person,
        'following': following,  # ✅ mavjud, o'zgarishsiz
    })


@login_required
def add_to_list(request, movie_id):
    if request.method == 'POST':
        from drama.models import Movie
        movie = get_object_or_404(Movie, id=movie_id)
        status = int(request.POST.get('status'))
        
        current_ep = int(request.POST.get('current_episode', 0))
        if current_ep > movie.episodes_count:
            current_ep = movie.episodes_count 
            
        if status == 2:
            current_ep = movie.episodes_count

        entry, created = UserMovieList.objects.update_or_create(
            profile=request.user.profile,
            movie=movie,
            defaults={
                'status': status,
                'current_episode': current_ep if status in [1, 2, 4] else 0,
                'score': request.POST.get('score') if status in [1, 2, 4] else None,
            }
        )
        
        if status == 2 and created:
            request.user.profile.xp += 100
            request.user.profile.save()

        messages.success(request, f"{movie.title} yangilandi!")
        return redirect('drama:movie_detail', slug=movie.slug)


def user_full_list(request, username):
    # 1. URL dagi username bo'yicha foydalanuvchini topamiz
    target_user = get_object_or_404(User, username=username)
    
    # 2. Shu foydalanuvchiga tegishli barcha kinolarni bitta so'rovda olamiz
    # select_related('movie') - SQL JOIN qilib bazani qiynamaydi
    user_items = UserMovieList.objects.filter(
        profile=target_user.profile
    ).select_related('movie').order_by('-updated_at')

    # 3. Ro'yxat egasi va ko'rayotgan odam bittaligini tekshiramiz
    is_owner = request.user == target_user

    # 4. Dinamik sarlavha (Title)
    if is_owner:
        page_title = "Mening ro'yxatim"
    else:
        page_title = f"{target_user.username}ning ro'yxati"

    context = {
    'target_user': target_user,
    'is_owner': is_owner,
    'title': page_title,
    'watching': user_items.filter(status=1),
    'completed': user_items.filter(status=2),
    'plan_to_watch': user_items.filter(status=3),
    'on_hold': user_items.filter(status=4),
    'dropped': user_items.filter(status=5),
    'total_count': user_items.count(), # Jami soni bitta so'rovda
}
    
    return render(request, 'users/my_full_list.html', context)


@login_required
def settings_view(request):
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)
        
        if u_form.is_valid() and p_form.is_valid():
            with transaction.atomic():
                u_form.save()
                p_form.save()
            messages.success(request, "Ma'lumotlaringiz muvaffaqiyatli yangilandi!")
            return redirect('users:settings')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'u_form': u_form,
        'p_form': p_form,
        'title': "Profil sozlamalari"
    }
    return render(request, 'users/settings.html', context)

# drama/views.py (yoki users/views.py) ichiga qo'shing
def subscription_view(request):
    # VIP narxi (Sizning kodingizda 15 deb belgilangan)
    context = {
        'vip_price': 15,
        'title': "VIP Obuna - Premium imkoniyatlar"
    }
    return render(request, 'pages/subscription.html', context)

# 🌟 VIP XARID QILISH FUNKSIYASI (TUZATILDI) 🌟
@login_required
def buy_premium(request):
    if request.method == 'POST':
        # VIP Narxini belgilaymiz (Agar sizda 1 Coin = 1000 so'm bo'lsa, 15 yozing)
        VIP_PRICE_1_MONTH = 15
        profile = request.user.profile

        if profile.balance >= VIP_PRICE_1_MONTH:
            with transaction.atomic():
                # 1. Pulni yechish
                profile.balance -= VIP_PRICE_1_MONTH
                
                # 2. Vaqtni hisoblash
                now = timezone.now()
                
                # MUHIM TUZATISH: premium_expires o'rniga premium_until yozildi
                if profile.is_premium and profile.premium_until:
                    # Bazadagi vaqt DateTime ekanligini tekshirib olamiz
                    if isinstance(profile.premium_until, datetime):
                        is_active = profile.premium_until > now
                    else:
                        is_active = profile.premium_until > now.date()
                    
                    # Agar VIP hali tugamagan bo'lsa, QOLGAN vaqtiga 30 kun qo'shamiz
                    if is_active:
                        profile.premium_until += timedelta(days=30)
                    else:
                        # Agar VIP muddati o'tib ketgan bo'lsa, BUGUNDAN boshlab 30 kun
                        profile.premium_until = now + timedelta(days=30)
                else:
                    # Hech qachon VIP olmagan bo'lsa, BUGUNDAN boshlab 30 kun
                    profile.premium_until = now + timedelta(days=30)
                
                # 3. VIP statusni qat'iy yoqish
                profile.is_premium = True
                
                profile.save()
            
            messages.success(request, "Tabriklaymiz! VIP obuna muvaffaqiyatli xarid qilindi va vaqt uzaytirildi 👑")
        else:
            messages.error(request, f"Hisobingizda mablag' yetarli emas! VIP narxi: {VIP_PRICE_1_MONTH} Coin.")
            
        return redirect('users:profile', username=request.user.username)


# 🌟 HISOBNI TO'LDIRISH FUNKSIYASI 🌟
@login_required
def topup_view(request):
    # Foydalanuvchida kutilayotgan so'rov bor-yo'qligini tekshiramiz
    pending_request = TopUpRequest.objects.filter(user=request.user, status='pending').first()

    if request.method == 'POST':
        # Agar pending holatidagi so'rov bo'lsa, xato beramiz
        if pending_request:
            messages.error(request, "Sizda allaqachon kutilayotgan so'rov mavjud!")
            return redirect('users:topup')
            
        form = TopUpRequestForm(request.POST, request.FILES)
        if form.is_valid():
            topup = form.save(commit=False)
            topup.user = request.user
            topup.save() # save() ishlaganda points avtomat hisoblanadi
            
            # ========================================================
            # 🌟 YANIGI QISM: ADMINGA TELEGRAM ORQALI XABAR YUBORISH 🌟
            # ========================================================
            msg = (
                f"🚨 <b>YANGI TO'LOV SO'ROVI!</b>\n\n"
                f"👤 <b>Foydalanuvchi:</b> @{request.user.username}\n"
                f"💵 <b>To'lov summasi:</b> {topup.amount_uzs} UZS\n"
                f"💎 <b>Beriladigan Coin:</b> {topup.points} Coin\n\n"
                f"Sizning aralashuvingiz kutilyapti! Chekni ko'rish va tasdiqlash uchun admin panelga kiring:\n"
                f"👉 https://drama.uz/admin/users/topuprequest/"
            )
            send_telegram_notification(msg)
            # ========================================================
            
            messages.success(request, "So'rovingiz muvaffaqiyatli yuborildi! Admin tasdiqlashini kuting.")
            return redirect('users:topup')
    else:
        form = TopUpRequestForm()

    context = {
        'form': form,
        'pending_request': pending_request,
        'title': "Hisobni to'ldirish"
    }
    return render(request, 'users/topup.html', context)