from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from django.views.generic import ListView, DetailView
from django.db.models import Q
from django.views.generic.base import View
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Prefetch # MUHIM: Prefetch shu yerdan keladi
from .models import Movie, Category, Genre, Actor, TopSlider, Rating, Review, Episode
from .forms import ReviewForm
# UserMovieList'ni users appidan import qilamiz
from users.models import UserMovieList 

# 404 xatolik
def error_404(request, exception):
    return render(request, '404.html', status=404)

@require_GET
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

# Jonli qidiruv (AJAX)
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

class GenreYearMixin:
    """Umumiy context ma'lumotlari"""
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['genres'] = Genre.objects.all()
        context['categories'] = Category.objects.all()
        context['years'] = Movie.objects.filter(is_draft=False)\
            .values_list("year", flat=True).distinct().order_by('-year')
        return context

class MoviesView(GenreYearMixin, ListView):
    model = Movie
    queryset = Movie.objects.filter(is_draft=False).order_by('-id')
    template_name = "movies/movie_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['top_sliders'] = TopSlider.objects.all()
        return context

# --- MANA SHU KLASS QO'SHILDI ---
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
        # Prefetch orqali izohlarni tartiblangan holda yuklaymiz
        return Movie.objects.filter(is_draft=False).select_related('category').prefetch_related(
            'genres',
            'main_actors',
            Prefetch(
                'reviews', 
                queryset=Review.objects.filter(parent=None).select_related('user').order_by('-id').prefetch_related(
                    Prefetch('replies', queryset=Review.objects.select_related('user').order_by('id'))
                )
            )
        )
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movie = self.get_object()
        episodes = movie.episodes.all().order_by('episode_number')
        context['episodes'] = episodes

        req_ep_num = self.request.GET.get('episode')
        active_episode = episodes.filter(episode_number=req_ep_num).first() if req_ep_num else episodes.first()
        context['active_episode'] = active_episode

        if active_episode:
            context['next_episode'] = episodes.filter(episode_number__gt=active_episode.episode_number).first()

        # VIP/Premium Tekshiruvi
        user = self.request.user
        is_premium_user = False
        if user.is_authenticated:
            if user.is_superuser:
                is_premium_user = True
            elif hasattr(user, 'profile'):
                is_premium_user = getattr(user.profile, 'is_currently_premium', False)

        is_restricted = False
        if movie.is_vip and active_episode and active_episode.episode_number > 1:
            if not is_premium_user:
                is_restricted = True
        context['is_restricted'] = is_restricted

        # Video linklar
        video_source = active_episode.video_embed_code if (active_episode and active_episode.video_embed_code) else movie.film_embed_code
        v720, v1080 = self.parse_video_links(video_source)
        context['video_720'], context['video_1080'] = v720, v1080
        
        # Userning shaxsiy listidagi holatini tekshirish
        if user.is_authenticated:
            context['user_movie_status'] = UserMovieList.objects.filter(profile=user.profile, movie=movie).first()

        return context

    def parse_video_links(self, source_text):
        if not source_text or "<div>" in source_text:
            return "", ""
        links = [l.strip() for l in source_text.split(',') if l.strip()]
        if not links: return "", ""
        v720 = links[0]
        v1080 = links[1] if len(links) > 1 else v720
        return v720, v1080

# --- LISTGA QO'SHISH LOGIKASI ---
@login_required
def add_to_list(request, movie_id):
    if request.method == 'POST':
        movie = get_object_or_404(Movie, id=movie_id)
        status = int(request.POST.get('status'))
        
        score = request.POST.get('score')
        episode = request.POST.get('current_episode', 0)

        # Update or Create
        entry, created = UserMovieList.objects.update_or_create(
            profile=request.user.profile,
            movie=movie,
            defaults={
                'status': status,
                'current_episode': int(episode) if status in [1, 2, 4] else 0,
                'score': float(score) if (status in [1, 2, 4] and score) else None,
            }
        )

        # XP Bonus: Agar yangi "Tugallangan" bo'lsa
        if status == 2 and created:
            request.user.profile.xp += 100
            request.user.profile.save()

        messages.success(request, f"'{movie.title}' ro'yxatingizga saqlandi!")
        return redirect('drama:movie_detail', slug=movie.slug)


class AddReview(View):
    def post(self, request, pk):
        # 1. Autentifikatsiya tekshiruvi
        if not request.user.is_authenticated:
            return HttpResponse("Ruxsat berilmagan", status=401)

        form = ReviewForm(request.POST)
        movie = get_object_or_404(Movie, id=pk)
        
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            review.movie = movie
            
            # 2. Parent (Reply) mantiqi
            parent_id = request.POST.get("parent")
            is_reply = False
            
            if parent_id:
                # FAQAT ADMIN JAVOB YOZA OLADI (Xavfsizlik)
                if not request.user.is_superuser:
                    return HttpResponse("Faqat admin javob yozishi mumkin", status=403)
                review.parent_id = int(parent_id)
                is_reply = True
            
            review.save()

            # 3. HTMX So'rovi bo'lsa
            if request.headers.get('HX-Request'):
                return render(request, 'movies/partials/comment_item.html', {
                    'review': review, 
                    'is_reply': is_reply
                })

        # 4. Standart so'rov bo'lsa (Fallback)
        return redirect(movie.get_absolute_url())

            
class FilterMoviesView(GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_template_names(self):
        # Agar so'rov HTMX orqali kelsa, faqat grid qismini qaytaramiz
        if self.request.headers.get("HX-Request"):
            return ["movies/partials/movie_grid.html"]
        return [self.template_name]

    def get_queryset(self):
        # URL'dan parametrlarni olish
        selected_years = self.request.GET.getlist("year")
        selected_genres = self.request.GET.getlist("genre")
        
        queryset = Movie.objects.filter(is_draft=False)

        # Yil bo'yicha filtr (bir nechta yil tanlanishi mumkin)
        if selected_years:
            queryset = queryset.filter(year__in=selected_years)

        # Janr bo'yicha filtr
        if selected_genres:
            queryset = queryset.filter(genres__slug__in=selected_genres)

        return queryset.distinct().order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Hozirgi tanlanganlarni shablonga qaytaramiz (tugmalarni rangli qilish uchun)
        context["selected_years"] = self.request.GET.getlist("year")
        context["selected_genres"] = self.request.GET.getlist("genre")
        return context

class ActorView(GenreYearMixin, DetailView):
    model = Actor
    template_name = 'movies/inson.html'
    slug_field = "slug"
    context_object_name = "actor"

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