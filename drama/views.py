# views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from django.db.models import Q, Count, Prefetch
from django.views.generic.base import View
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
# Tag modelini ham qo'shdik!
from .models import Movie, Category, Genre, Actor, ActorGift, TopSlider, Rating, Review, Episode, Tag
from .forms import ReviewForm
from users.models import UserMovieList
from django.db import transaction

# 1. MIXINS (Hamma Viewlardan tepada bo'lishi shart)
class GenreYearMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Keshdan olish yoki bazadan o'qib keshga yozish
        context['genres'] = cache.get_or_set('all_genres', Genre.objects.all(), 86400)
        context['categories'] = cache.get_or_set('all_categories', Category.objects.all(), 86400)
        
        # Murakkab so'rovlarni keshda saqlash serverni juda yengillashtiradi
        years = cache.get('movie_years')
        if not years:
            years = list(Movie.objects.filter(is_draft=False).values_list("year", flat=True).distinct().order_by('-year'))
            cache.set('movie_years', years, 86400)
        context['years'] = years

        countries = cache.get('movie_countries')
        if not countries:
            countries = list(Movie.objects.filter(is_draft=False).values_list("country", flat=True).distinct().order_by('country'))
            cache.set('movie_countries', countries, 86400)
        context['countries'] = countries
        
        return context

# 2. TIZIM FUNKSIYALARI
def error_404(request, exception):
    return render(request, '404.html', status=404)

@require_GET
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /users/",
        "Allow: /",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
        "Host: drama.uz"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

def live_search(request):
    query = request.GET.get('q', '').strip()
    if len(query) > 1:
        movies = Movie.objects.filter(
            Q(title__icontains=query) | Q(original_title__icontains=query),
            is_draft=False
        ).distinct()[:5]
        
        results = [{
            'title': m.title,
            'url': m.get_absolute_url(),
            'poster': m.poster.url if m.poster else "",
            'year': m.year
        } for m in movies]
        return JsonResponse({'status': 'ok', 'results': results})
    return JsonResponse({'status': 'empty', 'results': []})

# 3. ASOSIY VIEWLAR (Klasslar)
class MoviesView(GenreYearMixin, ListView):
    model = Movie
    queryset = Movie.objects.filter(is_draft=False).select_related('category').prefetch_related('genres', 'tags').order_by('-id')
    template_name = "index.html"  # MANA SHU YERNI O'ZGARTIRING
    context_object_name = "movies"
    paginate_by = 12

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_sliders'] = TopSlider.objects.all()
        return context

# drama/views.py
class TagDetailView(GenreYearMixin, ListView):
    template_name = "movies/movie_list.html" # Mavjud list shablonini ishlatamiz
    context_object_name = "movies"
    paginate_by = 12

    def get_queryset(self):
        # Tegni slug orqali topamiz
        self.tag = get_object_or_404(Tag, slug=self.kwargs.get("slug"))
        # Shu tegga tegishli barcha kinolarni -id bo'yicha saralab olamiz
        return Movie.objects.filter(tags=self.tag, is_draft=False).order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Sahifa sarlavhasini dinamik o'zgartiramiz
        context["title"] = f"#{self.tag.name} mavzusidagi barcha dramalar"
        return context

class GenreDetailView(GenreYearMixin, ListView):
    template_name = "movies/movie_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_queryset(self):
        self.genre = get_object_or_404(Genre, slug=self.kwargs.get("slug"))
        return Movie.objects.filter(genres=self.genre, is_draft=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = f"{self.genre.name} janridagi kinolar"
        return context

class MovieDetailView(GenreYearMixin, DetailView):
    model = Movie
    queryset = Movie.objects.filter(is_draft=False)
    slug_field = "slug"
    template_name = "movies/movie_detail.html"
    context_object_name = "movie"

    def get_queryset(self):
        # Epizodlarni ham prefetch qilamiz (N+1 muammosini hal qiladi)
        return Movie.objects.filter(is_draft=False).select_related('category').prefetch_related(
            'genres', 'main_actors', 'tags', 'episodes' # Epizodlar shu yerga qo'shildi
        ).prefetch_related(
            Prefetch('reviews', queryset=Review.objects.filter(parent=None).select_related('user').order_by('-id'))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # FIX: self.get_object() ikkinchi DB so'rovini bajaradi.
        # DetailView.get() self.object ni set qiladi, uni ishlatamiz.
        movie = self.object
        episodes = movie.episodes.all().order_by('episode_number')
        context['episodes'] = episodes

        req_ep_num = self.request.GET.get('episode')
        active_episode = episodes.filter(episode_number=req_ep_num).first() if req_ep_num else episodes.first()
        context['active_episode'] = active_episode

        if active_episode:
            context['next_episode'] = episodes.filter(episode_number__gt=active_episode.episode_number).first()

        user = self.request.user
        
        # ==========================================
        # CROWDFUNDING TEKSHIRUVI
        # ==========================================
        funding_project = getattr(movie, 'funding_project', None)
        context['funding_project'] = funding_project
        
        user_has_access = False
        if user.is_authenticated and funding_project:
            user_has_access = funding_project.has_access(user.profile)
        context['user_has_access'] = user_has_access

        # ==========================================
        # VIP TEKSHIRUVI
        # ==========================================
        is_premium_user = False
        if user.is_authenticated:
            if user.is_superuser:
                is_premium_user = True
            elif hasattr(user, 'profile'):
                is_premium_user = getattr(user.profile, 'is_currently_premium', False)

        # ==========================================
        # 🌟 QULFLASH MANTIQI (RESTRICTION) - TUZATILDI 🌟
        # ==========================================
        is_restricted = False
        restriction_type = None

        # 1-10 qismlar tekin; 11+ qismdan himoya boshlanadi
        if active_episode and active_episode.episode_number > 10:

            # QOIDA 1: Agar serial Crowdfunding (Pul yig'ish) da bo'lsa
            if funding_project:
                if not user.is_authenticated or not user_has_access:
                    is_restricted = True
                    restriction_type = 'funding'

            # QOIDA 2: Agar serial VIP bo'lsa (va u Crowdfunding bo'lmasa)
            elif movie.is_vip:
                if not user.is_authenticated or not is_premium_user:
                    is_restricted = True
                    restriction_type = 'vip'

        context['is_restricted'] = is_restricted
        context['restriction_type'] = restriction_type

        # ==========================================
        # PLEYER URL LARI VA BOSHQA NARSALAR
        # ==========================================
        video_source = active_episode.video_embed_code if (active_episode and active_episode.video_embed_code) else movie.film_embed_code
        v720, v1080 = self.parse_video_links(video_source)
        context['video_720'], context['video_1080'] = v720, v1080
        
        if user.is_authenticated:
            context['user_movie_status'] = UserMovieList.objects.filter(profile=user.profile, movie=movie).first()

        movie_tags_ids = movie.tags.values_list('id', flat=True)
        similar_movies = Movie.objects.filter(tags__in=movie_tags_ids, is_draft=False)\
            .exclude(id=movie.id).annotate(same_tags=Count('tags')).order_by('-same_tags', '-mdl_rank')[:6]
            
        context['similar_movies'] = similar_movies
        return context

    def parse_video_links(self, source_text):
        if not source_text or "<div>" in source_text:
            return "", ""
        
        # split va strip operatsiyalarini bir marta bajarish
        links = [l.strip() for l in source_text.split(',') if l.strip()]
        if not links:
            return "", ""
            
        v720 = links[0]
        # Agar ikkinchi link bo'lsa uni oladi, bo'lmasa birinchisini FHD deb oladi
        v1080 = links[1] if len(links) > 1 else v720
        return v720, v1080
        
# 4. FUNKSIYA ASOSIDAGI VIEWLAR (FBV)
@login_required
def add_to_list(request, movie_id):
    if request.method == 'POST':
        from drama.models import Movie
        movie = get_object_or_404(Movie, id=movie_id)
        
        # 1. STATUSNI XAVFSIZ OLISH (Faqat raqam kelishini kafolatlash)
        try:
            status = int(request.POST.get('status', 0))
        except ValueError:
            messages.error(request, "Noto'g'ri status tanlandi.")
            return redirect('drama:movie_detail', slug=movie.slug)
            
        # 2. QISMLARNI XAVFSIZ OLISH
        try:
            current_ep = int(request.POST.get('current_episode', 0))
        except ValueError:
            current_ep = 0
            
        if current_ep > movie.episodes_count:
            current_ep = movie.episodes_count 
            
        if status == 2: # Ko'rib tugallangan
            current_ep = movie.episodes_count

        # 3. 🌟 SCORE (BAHO) UCHUN ASOSIY XAVFSIZLIK FILTRI 🌟
        raw_score = request.POST.get('score')
        clean_score = None # Odatiy holatda bo'sh turadi

        if status in [1, 2, 4] and raw_score:
            try:
                # Matnni raqamga (float) o'tkazishga urinib ko'ramiz
                parsed_score = float(raw_score)
                
                # Modelda 1.0 dan 10.0 gacha deb belgilangan. Shuni tekshiramiz.
                if 1.0 <= parsed_score <= 10.0:
                    clean_score = parsed_score
                else:
                    messages.warning(request, "Baho 1 va 10 oralig'ida bo'lishi kerak. Kino bahosiz saqlandi.")
            except ValueError:
                # Agar raqam o'rniga harf yoki bo'sh joy kelsa:
                messages.warning(request, "Noto'g'ri baho kiritildi. Kino bahosiz saqlandi.")

        # 4. BAZAGA XAVFSIZ YOZISH
        entry, created = UserMovieList.objects.update_or_create(
            profile=request.user.profile,
            movie=movie,
            defaults={
                'status': status,
                'current_episode': current_ep if status in [1, 2, 4] else 0,
                'score': clean_score, # Filtrlangan va xavfsiz bahoni beramiz
            }
        )
        
        # 5. XP QO'SHISH VA TEZLIKNI OSHIRISH
        if status == 2 and created:
            request.user.profile.xp += 100
            # Faqatgina 'xp' maydonini yangilaymiz (Tezroq ishlashi uchun update_fields)
            request.user.profile.save(update_fields=['xp'])

        messages.success(request, f"'{movie.title}' ro'yxatingizga saqlandi!")
        return redirect('drama:movie_detail', slug=movie.slug)
        
class MovieReviewsView(GenreYearMixin, ListView):
    template_name = "movies/movie_reviews.html"
    context_object_name = "reviews"
    paginate_by = 15 # Bitta sahifada 15 ta fikr chiqadi

    def get_queryset(self):
        # 1. Kinoni slug orqali topib olamiz
        self.movie = get_object_or_404(Movie, slug=self.kwargs.get("slug"), is_draft=False)
        
        # 2. Shu kinoga tegishli, faqat asosiy izohlarni (parent=None) eng yangilaridan boshlab olamiz
        return Review.objects.filter(movie=self.movie, parent=None).select_related('user').order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Template'da kino rasmi va nomini chiqarish uchun 'movie' ni context'ga uzatamiz
        context["movie"] = self.movie 
        context["title"] = f"{self.movie.title} - Barcha fikrlar"
        return context

class AddReview(View):
    def post(self, request, pk):
        if not request.user.is_authenticated:
            return HttpResponse("Ruxsat berilmagan", status=401)
        form = ReviewForm(request.POST)
        movie = get_object_or_404(Movie, id=pk)
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            review.movie = movie
            parent_id = request.POST.get("parent")
            is_reply = False
            if parent_id:
                if not request.user.is_superuser:
                    return HttpResponse("Faqat admin javob yozishi mumkin", status=403)
                review.parent_id = int(parent_id)
                is_reply = True
            review.save()
            if request.headers.get('HX-Request'):
                return render(request, 'movies/partials/comment_item.html', {
                    'review': review, 'is_reply': is_reply
                })
        return redirect(movie.get_absolute_url())

# drama/views.py

class FilterMoviesView(GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["movies/partials/movie_grid.html"]
        return [self.template_name]

    def get_queryset(self):
        # Parametrlarni olish
        year = self.request.GET.getlist("year")
        genre = self.request.GET.getlist("genre")
        country = self.request.GET.get("country")
        min_rating = self.request.GET.get("min_rating")

        queryset = Movie.objects.filter(is_draft=False).select_related('category').prefetch_related('genres', 'tags').order_by('-id')

        # Filtrlar mantiqi
        if year:
            queryset = queryset.filter(year__in=year)
        if genre:
            queryset = queryset.filter(genres__slug__in=genre)
        if country:
            queryset = queryset.filter(country=country)
        if min_rating:
            queryset = queryset.filter(mdl_rank__gte=float(min_rating))

        return queryset.distinct().order_by('-created_at')

class ActorView(GenreYearMixin, DetailView):
    model = Actor
    template_name = 'movies/inson.html'
    slug_field = "slug"
    context_object_name = "actor"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # FIX: self.get_object() o'rniga self.object (qo'shimcha DB so'rovini oldini olish)
        actor = self.object

        all_movies = Movie.objects.filter(
            Q(main_actors=actor) | Q(actors=actor),
            is_draft=False
        ).distinct().order_by('-year', '-created_at')

        context['all_movies'] = all_movies
        context['all_movies_count'] = all_movies.count()
        return context

# Yaxshilangan va mustahkamlangan send_gift_to_actor funksiyasi
@login_required
def send_gift_to_actor(request, actor_id):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. BAZADAN MA'LUMOTLARNI OLISH (Eng birinchi shu qilinadi)
                actor = Actor.objects.select_for_update().get(id=actor_id)
                profile = request.user.profile
                gift_type = request.POST.get('gift')
                
                # 2. NARXLARNI BELGILASH
                gift_prices = {
                    'rose': 5,
                    'coffee': 5,
                    'crown': 20
                }
                price = gift_prices.get(gift_type)
                
                # 3. NARXNI TEKSHIRISH (Agar notanish sovg'a jo'natilsa)
                if not price:
                    messages.error(request, "Noto'g'ri sovg'a tanlandi.")
                    return redirect(actor.get_absolute_url())

                # 4. BALANSNI TEKSHIRISH VA TRANZAKSIYA
                if profile.balance >= price:
                    # Userdan pulni yechish
                    profile.balance -= price
                    profile.save(update_fields=['balance'])
                    
                    # Aktyorning sovg'alarini ko'paytirish
                    current_gifts = actor.total_gifts or 0
                    actor.total_gifts = current_gifts + price
                    actor.save(update_fields=['total_gifts'])

                    # JURNALGA YOZISH
                    ActorGift.objects.create(
                        user=request.user,
                        actor=actor,
                        gift_type=gift_type,
                        price=price
                    )

                    # Muvaffaqiyatli xabar
                    gift_names = {'rose': 'Gul 🌹', 'coffee': 'Qahva ☕', 'crown': 'Toj 👑'}
                    messages.success(request, f"{actor.name} ga {gift_names[gift_type]} yubordingiz! U bundan juda xursand bo'ladi 🎉")
                else:
                    # Pul yetmasa
                    messages.error(request, "Sovg'a yuborish uchun Coin yetarli emas. Iltimos hisobingizni to'ldiring.")
                    
        except Actor.DoesNotExist:
            messages.error(request, "Aktyor topilmadi.")
            return redirect('drama:explore')
            
        return redirect(actor.get_absolute_url())

class Search(GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12
    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        if not q: return Movie.objects.none()
        return Movie.objects.filter(
            Q(title__icontains=q) | Q(original_title__icontains=q),
            is_draft=False
        ).distinct().order_by('-created_at')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q")
        context["title"] = f"'{context['q']}' bo'yicha qidiruv natijalari"
        return context