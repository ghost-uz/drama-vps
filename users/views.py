from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.auth.models import User
from .forms import UserRegisterForm, UserUpdateForm, ProfileUpdateForm
from .models import UserMovieList


def register(request):
    if request.user.is_authenticated:
        return redirect('drama:home')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic(): # Hammasi yoki hech narsa
                    form.save()
                username = form.cleaned_data.get('username')
                messages.success(request, f"Xush kelibsiz {username}!")
                return redirect('login')
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {e}")
    else:
        form = UserRegisterForm()
    
    return render(request, 'users/register.html', {'form': form})

def profile_view(request, username):
    person = get_object_or_404(User, username=username)
    profile = person.profile
    
    # Profil egasining ro'yxatidagi oxirgi 5 ta harakat
    watched_history = UserMovieList.objects.filter(profile=profile).select_related('movie')[:5]
    
    # Statistikalar
    watched_count = UserMovieList.objects.filter(profile=profile, status=2).count() # Tugallanganlar
    
    context = {
        'person': person,
        'profile': profile,
        'watched_history': watched_history,
        'watched_count': watched_count,
    }
    return render(request, 'users/profile.html', context)

@login_required
def add_to_list(request, movie_id):
    """
    Kino sahifasidan kelgan statuslarni saqlash funksiyasi
    """
    if request.method == 'POST':
        movie = get_object_or_404(Movie, id=movie_id)
        status = int(request.POST.get('status'))
        
        # UserMovieList yaratish yoki yangilash
        entry, created = UserMovieList.objects.update_or_create(
            profile=request.user.profile,
            movie=movie,
            defaults={
                'status': status,
                'current_episode': request.POST.get('current_episode', 0) if status in [1, 2, 4] else 0,
                'score': request.POST.get('score') if status in [1, 2, 4] else None,
            }
        )
        
        # Mantiq: Agar rasm "Ko'rib tugallangan" (2) bo'lsa, XP ball berish
        if status == 2 and created:
            request.user.profile.xp += 100 # Birinchi marta tugatgani uchun bonus
            request.user.profile.save()

        messages.success(request, f"{movie.title} ro'yxatga qo'shildi!")
        return redirect('drama:movie_detail', slug=movie.slug)


@login_required
def my_full_list(request):
    """Barcha statuslar bo'yicha guruhlangan ro'yxat"""
    user_list = UserMovieList.objects.filter(profile=request.user.profile).select_related('movie')
    
    context = {
        'watching': user_list.filter(status=1),
        'completed': user_list.filter(status=2),
        'plan_to_watch': user_list.filter(status=3),
        'on_hold': user_list.filter(status=4),
        'dropped': user_list.filter(status=5),
        'title': "Mening ro'yxatim"
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