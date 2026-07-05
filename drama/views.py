# views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView
from django.views.generic.base import View
from django_ratelimit.decorators import ratelimit

from core.ratelimit import ip_key, rate, user_or_ip_key
from users.models import CoinTransaction, UserMovieList
from users.services import wallet

from .cache import catalog_version, get_or_set_catalog
from .forms import ReviewForm

# Tag modelini ham qo'shdik!
from .models import (
    Actor,
    ActorGift,
    Category,
    Genre,
    Movie,
    Review,
    Tag,
    TopSlider,
)


# 1. MIXINS (Hamma Viewlardan tepada bo'lishi shart)
class GenreYearMixin:
    """Katalog filtr-ma'lumotlari — versiyalangan kesh [P9-T1].

    Kalitlar catalog:v{n}:* — Movie/Genre/... o'zgarganda signal versiyani
    bump qiladi, ro'yxatlar DARHOL yangilanadi (oldin 86400s eskirish edi).
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["genres"] = get_or_set_catalog("genres", lambda: list(Genre.objects.all()))
        context["categories"] = get_or_set_catalog(
            "categories", lambda: list(Category.objects.all())
        )
        context["years"] = get_or_set_catalog(
            "years",
            lambda: list(
                Movie.objects.published()
                .values_list("year", flat=True)
                .distinct()
                .order_by("-year")
            ),
        )
        context["countries"] = get_or_set_catalog(
            "countries",
            lambda: list(
                Movie.objects.published()
                .values_list("country", flat=True)
                .distinct()
                .order_by("country")
            ),
        )
        # Fragment-kesh kaliti uchun ({% cache ... catalog_ver %}) [P9-T1]
        context["catalog_ver"] = catalog_version()

        return context


# 2. TIZIM FUNKSIYALARI
def error_404(request, exception):
    return render(request, "404.html", status=404)


@require_GET
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /users/",
        "Allow: /",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap-video.xml",
        "Host: drama.uz",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@ratelimit(key=ip_key, rate=rate, group="live_search", method="GET", block=True)
def live_search(request):
    query = request.GET.get("q", "").strip()
    if len(query) > 1:
        movies = (
            Movie.objects.published()
            .filter(Q(title__icontains=query) | Q(original_title__icontains=query))
            .distinct()[:5]
        )

        results = [
            {
                "title": m.title,
                "url": m.get_absolute_url(),
                "poster": m.poster.url if m.poster else "",
                "year": m.year,
            }
            for m in movies
        ]
        return JsonResponse({"status": "ok", "results": results})
    return JsonResponse({"status": "empty", "results": []})


# 3. ASOSIY VIEWLAR (Klasslar)
class MoviesView(GenreYearMixin, ListView):
    model = Movie
    # [P9-T2] Karta faqat poster/title/yil/davlat/qism-soni ko'rsatadi:
    # select_related(category) + prefetch(genres, tags) ISHLATILMAY turib
    # har sahifada 2 ta bekor so'rov qo'shayotgan edi — olib tashlandi.
    queryset = Movie.objects.published().with_card_data().order_by("-id")
    template_name = "index.html"  # MANA SHU YERNI O'ZGARTIRING
    context_object_name = "movies"
    paginate_by = 12

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["top_sliders"] = TopSlider.objects.all()
        # 'Davom ettirish' karuseli — tugatilmagan progresslar (indeks: user, -updated_at)
        if self.request.user.is_authenticated:
            from users.models import WatchProgress

            context["continue_watching"] = (
                WatchProgress.objects.filter(user=self.request.user, completed=False)
                .select_related("episode", "episode__movie")
                .order_by("-updated_at")[:12]
            )
        return context


# drama/views.py
class TagDetailView(GenreYearMixin, ListView):
    template_name = "movies/movie_list.html"  # Mavjud list shablonini ishlatamiz
    context_object_name = "movies"
    paginate_by = 12

    def get_queryset(self):
        # Tegni slug orqali topamiz
        self.tag = get_object_or_404(Tag, slug=self.kwargs.get("slug"))
        # select_related(category): shablon kategoriya nomini ko'rsatadi [P9-T2]
        return (
            Movie.objects.published()
            .filter(tags=self.tag)
            .select_related("category")
            .with_card_data()
            .order_by("-id")
        )

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
        # order_by'siz pagination beqaror edi (UnorderedObjectListWarning) [P5-T4]
        return (
            Movie.objects.published()
            .filter(genres=self.genre)
            .select_related("category")
            .with_card_data()
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = f"{self.genre.name} janridagi kinolar"
        return context


class MovieDetailView(GenreYearMixin, DetailView):
    model = Movie
    queryset = Movie.objects.published()
    slug_field = "slug"
    template_name = "movies/movie_detail.html"
    context_object_name = "movie"

    def get_queryset(self):
        # Epizodlarni ham prefetch qilamiz (N+1 muammosini hal qiladi)
        # [P9-T2] funding_project (reverse O2O) select_related — getattr'dagi
        # alohida so'rov yo'qoladi; review'larga user__profile (avatar) va
        # replies (admin javoblari) prefetch — komment N+1 yopiladi.
        return (
            Movie.objects.published()
            .select_related("category", "funding_project")
            .prefetch_related(
                "genres",
                "main_actors",
                "tags",
                "episodes",  # Epizodlar shu yerga qo'shildi
            )
            .prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=Review.objects.filter(parent=None)
                    .select_related("user", "user__profile")
                    .prefetch_related(
                        Prefetch(
                            "replies",
                            queryset=Review.objects.select_related("user").order_by("id"),
                        )
                    )
                    .order_by("-id"),
                )
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # FIX: self.get_object() ikkinchi DB so'rovini bajaradi.
        # DetailView.get() self.object ni set qiladi, uni ishlatamiz.
        movie = self.object
        # [P9-T2] prefetch keshi Meta.ordering (episode_number) bilan keladi;
        # .order_by()/.filter() prefetch ustida YANGI so'rov ochardi — endi
        # aktiv/keyingi qism Python'da tanlanadi (0 qo'shimcha so'rov).
        episodes = list(movie.episodes.all())
        context["episodes"] = episodes

        req_ep_num = self.request.GET.get("episode")
        if req_ep_num:
            active_episode = next(
                (e for e in episodes if str(e.episode_number) == req_ep_num), None
            )
        else:
            active_episode = episodes[0] if episodes else None
        context["active_episode"] = active_episode

        if active_episode:
            context["next_episode"] = next(
                (e for e in episodes if e.episode_number > active_episode.episode_number),
                None,
            )

        user = self.request.user

        # ==========================================
        # CROWDFUNDING TEKSHIRUVI
        # ==========================================
        funding_project = getattr(movie, "funding_project", None)
        context["funding_project"] = funding_project

        user_has_access = False
        if user.is_authenticated and funding_project:
            user_has_access = funding_project.has_access(user.profile)
        context["user_has_access"] = user_has_access

        # ==========================================
        # QULFLASH MANTIQI — yagona service (HTML + API bir manba) [P2-T4]
        # ==========================================
        if active_episode:
            from drama.services.playback import get_episode_access

            allowed, restriction_type = get_episode_access(user, active_episode)
            is_restricted = not allowed
        else:
            is_restricted = False
            restriction_type = None

        context["is_restricted"] = is_restricted
        context["restriction_type"] = restriction_type

        # ==========================================
        # PLEYER URL LARI VA BOSHQA NARSALAR
        # ==========================================
        if is_restricted:
            context.update(
                {
                    "use_bunny": False,
                    "video_hls": "",
                    "video_720": "",
                    "video_1080": "",
                    "video_thumbnail": "",
                    "video_preview": "",
                }
            )
        else:
            from drama.bunny_stream import get_all_urls, is_configured, token_user_ip

            # Aktiv epizod yoki filmning Bunny Video ID sini aniqlaymiz
            vid = None
            if active_episode and active_episode.bunny_video_id:
                vid = active_episode.bunny_video_id
            elif not active_episode and movie.bunny_video_id:
                vid = movie.bunny_video_id

            if vid and is_configured():
                # [P4-T1] HTML pleyer ham imzolangan URL oladi (API bilan bir xil)
                urls = get_all_urls(vid, user_ip=token_user_ip(self.request))
                context.update(
                    {
                        "use_bunny": True,
                        "video_hls": urls["hls"],
                        "video_720": urls["play_720"],
                        "video_1080": urls["play_1080"],
                        "video_thumbnail": urls["thumbnail"],
                        "video_preview": urls["preview"],
                    }
                )
            else:
                # Eski tizimga fallback (Contabo URL yoki embed kod)
                video_source = (
                    active_episode.video_embed_code
                    if (active_episode and active_episode.video_embed_code)
                    else movie.film_embed_code
                )
                v720, v1080 = self.parse_video_links(video_source)
                context.update(
                    {
                        "use_bunny": False,
                        "video_hls": "",
                        "video_720": v720,
                        "video_1080": v1080,
                        "video_thumbnail": "",
                        "video_preview": "",
                    }
                )

        if user.is_authenticated:
            context["user_movie_status"] = UserMovieList.objects.filter(
                profile=user.profile, movie=movie
            ).first()

        # O'xshash kinolar — og'ir annotate-Count so'rovi. ID'lar versiyalangan
        # keshda; obyektlar arzon pk-so'rov bilan YANGI olinadi (reyting/poster
        # .update() bilan o'zgarsa ham kartada eskirmaydi) [P9-T1]
        def _similar_ids():
            movie_tags_ids = movie.tags.values_list("id", flat=True)
            return list(
                Movie.objects.published()
                .filter(tags__in=movie_tags_ids)
                .exclude(id=movie.id)
                .annotate(same_tags=Count("tags"))
                .order_by("-same_tags", "-mdl_rank")
                .values_list("id", flat=True)[:6]
            )

        similar_ids = get_or_set_catalog(f"similar:{movie.pk}", _similar_ids)
        similar_map = {
            m.pk: m for m in Movie.objects.published().with_card_data().filter(id__in=similar_ids)
        }
        context["similar_movies"] = [similar_map[i] for i in similar_ids if i in similar_map]

        # SEO structured data [P5-T4] — xavfsiz JSON-LD (drama/seo.py)
        from drama.seo import movie_jsonld

        context["seo_jsonld"] = movie_jsonld(self.request, movie, active_episode)

        # Pleyer: davom ettirish pozitsiyasi (WatchProgress, P1-T3) [P5-T2]
        resume_position = 0
        if active_episode and user.is_authenticated:
            from users.models import WatchProgress

            progress = WatchProgress.objects.filter(user=user, episode=active_episode).first()
            if progress and not progress.completed:
                resume_position = progress.position_seconds
        context["resume_position"] = resume_position
        return context

    def parse_video_links(self, source_text):
        if not source_text or "<div>" in source_text:
            return "", ""

        # split va strip operatsiyalarini bir marta bajarish
        links = [link.strip() for link in source_text.split(",") if link.strip()]
        if not links:
            return "", ""

        v720 = links[0]
        # Agar ikkinchi link bo'lsa uni oladi, bo'lmasa birinchisini FHD deb oladi
        v1080 = links[1] if len(links) > 1 else v720
        return v720, v1080


# 4. FUNKSIYA ASOSIDAGI VIEWLAR (FBV)
@login_required
def add_to_list(request, movie_id):
    if request.method == "POST":
        from drama.models import Movie

        movie = get_object_or_404(Movie, id=movie_id)

        # 1. STATUSNI XAVFSIZ OLISH (Faqat raqam kelishini kafolatlash)
        try:
            status = int(request.POST.get("status", 0))
        except ValueError:
            messages.error(request, "Noto'g'ri status tanlandi.")
            return redirect("drama:movie_detail", slug=movie.slug)

        # 2. QISMLARNI XAVFSIZ OLISH
        try:
            current_ep = int(request.POST.get("current_episode", 0))
        except ValueError:
            current_ep = 0

        if current_ep > movie.episodes_count:
            current_ep = movie.episodes_count

        if status == 2:  # Ko'rib tugallangan
            current_ep = movie.episodes_count

        # 3. 🌟 SCORE (BAHO) UCHUN ASOSIY XAVFSIZLIK FILTRI 🌟
        raw_score = request.POST.get("score")
        clean_score = None  # Odatiy holatda bo'sh turadi

        if status in [1, 2, 4] and raw_score:
            try:
                # Matnni raqamga (float) o'tkazishga urinib ko'ramiz
                parsed_score = float(raw_score)

                # Modelda 1.0 dan 10.0 gacha deb belgilangan. Shuni tekshiramiz.
                if 1.0 <= parsed_score <= 10.0:
                    clean_score = parsed_score
                else:
                    messages.warning(
                        request, "Baho 1 va 10 oralig'ida bo'lishi kerak. Kino bahosiz saqlandi."
                    )
            except ValueError:
                # Agar raqam o'rniga harf yoki bo'sh joy kelsa:
                messages.warning(request, "Noto'g'ri baho kiritildi. Kino bahosiz saqlandi.")

        # 4. BAZAGA XAVFSIZ YOZISH
        entry, created = UserMovieList.objects.update_or_create(
            profile=request.user.profile,
            movie=movie,
            defaults={
                "status": status,
                "current_episode": current_ep if status in [1, 2, 4] else 0,
                "score": clean_score,  # Filtrlangan va xavfsiz bahoni beramiz
            },
        )

        # 5. XP QO'SHISH VA TEZLIKNI OSHIRISH
        if status == 2 and created:
            request.user.profile.xp += 100
            # Faqatgina 'xp' maydonini yangilaymiz (Tezroq ishlashi uchun update_fields)
            request.user.profile.save(update_fields=["xp"])

        messages.success(request, f"'{movie.title}' ro'yxatingizga saqlandi!")
        return redirect("drama:movie_detail", slug=movie.slug)


class MovieReviewsView(GenreYearMixin, ListView):
    template_name = "movies/movie_reviews.html"
    context_object_name = "reviews"
    paginate_by = 15  # Bitta sahifada 15 ta fikr chiqadi

    def get_queryset(self):
        # 1. Kinoni slug orqali topib olamiz
        self.movie = get_object_or_404(Movie.objects.published(), slug=self.kwargs.get("slug"))

        # 2. Shu kinoga tegishli, faqat asosiy izohlarni (parent=None) eng yangilaridan boshlab olamiz
        # [P9-T2] user__profile (avatar) + replies prefetch — komment N+1 yo'q
        return (
            Review.objects.filter(movie=self.movie, parent=None)
            .select_related("user", "user__profile")
            .prefetch_related(
                Prefetch("replies", queryset=Review.objects.select_related("user").order_by("id"))
            )
            .order_by("-id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Template'da kino rasmi va nomini chiqarish uchun 'movie' ni context'ga uzatamiz
        context["movie"] = self.movie
        context["title"] = f"{self.movie.title} - Barcha fikrlar"
        return context


class AddReview(View):
    @method_decorator(
        ratelimit(key=user_or_ip_key, rate=rate, group="review", method="POST", block=True)
    )
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
            if request.headers.get("HX-Request"):
                return render(
                    request,
                    "movies/partials/comment_item.html",
                    {"review": review, "is_reply": is_reply},
                )
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

        # [P9-T2] Karta kategoriya/janr ko'rsatmaydi — select/prefetch bekor edi;
        # with_card_data() qism-soni annotatsiyasini beradi.
        queryset = Movie.objects.published().with_card_data().order_by("-id")

        # Filtrlar mantiqi
        if year:
            queryset = queryset.filter(year__in=year)
        if genre:
            queryset = queryset.filter(genres__slug__in=genre)
        if country:
            queryset = queryset.filter(country=country)
        if min_rating:
            queryset = queryset.filter(mdl_rank__gte=float(min_rating))

        return queryset.distinct().order_by("-created_at")


class ActorView(GenreYearMixin, DetailView):
    model = Actor
    template_name = "movies/inson.html"
    slug_field = "slug"
    context_object_name = "actor"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # FIX: self.get_object() o'rniga self.object (qo'shimcha DB so'rovini oldini olish)
        actor = self.object

        # [P9-T2] list(): shablon to'liq iteratsiya qiladi — alohida COUNT
        # so'rovi o'rniga len() (2 so'rov -> 1).
        all_movies = list(
            Movie.objects.published()
            .filter(Q(main_actors=actor) | Q(actors=actor))
            .distinct()
            .order_by("-year", "-created_at")
        )

        context["all_movies"] = all_movies
        context["all_movies_count"] = len(all_movies)
        return context


# Yaxshilangan va mustahkamlangan send_gift_to_actor funksiyasi
@login_required
@ratelimit(key=user_or_ip_key, rate=rate, group="gift", method="POST", block=True)
def send_gift_to_actor(request, actor_id):
    if request.method == "POST":
        try:
            with transaction.atomic():
                # 1. BAZADAN MA'LUMOTLARNI OLISH (Eng birinchi shu qilinadi)
                actor = Actor.objects.select_for_update().get(id=actor_id)
                profile = request.user.profile
                gift_type = request.POST.get("gift")

                # 2. NARXLARNI BELGILASH
                gift_prices = {"rose": 5, "coffee": 5, "crown": 20}
                price = gift_prices.get(gift_type)

                # 3. NARXNI TEKSHIRISH (Agar notanish sovg'a jo'natilsa)
                if not price:
                    messages.error(request, "Noto'g'ri sovg'a tanlandi.")
                    return redirect(actor.get_absolute_url())

                # 4. BALANSNI TEKSHIRISH VA YECHISH (ledger orqali, atomik)
                try:
                    wallet.debit(
                        profile,
                        price,
                        CoinTransaction.Type.GIFT,
                        description=f"{actor.name} ga sovg'a ({gift_type})",
                        reference=f"actor:{actor.id}",
                    )
                except wallet.InsufficientFundsError:
                    messages.error(
                        request,
                        "Sovg'a yuborish uchun Coin yetarli emas. Iltimos hisobingizni to'ldiring.",
                    )
                    return redirect(actor.get_absolute_url())

                # Aktyorning sovg'alarini ko'paytirish
                current_gifts = actor.total_gifts or 0
                actor.total_gifts = current_gifts + price
                actor.save(update_fields=["total_gifts"])

                # JURNALGA YOZISH
                ActorGift.objects.create(
                    user=request.user, actor=actor, gift_type=gift_type, price=price
                )

                # Muvaffaqiyatli xabar
                gift_names = {"rose": "Gul 🌹", "coffee": "Qahva ☕", "crown": "Toj 👑"}
                messages.success(
                    request,
                    f"{actor.name} ga {gift_names[gift_type]} yubordingiz! U bundan juda xursand bo'ladi 🎉",
                )

        except Actor.DoesNotExist:
            messages.error(request, "Aktyor topilmadi.")
            return redirect("drama:explore")

        return redirect(actor.get_absolute_url())


class Search(GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        if not q:
            return Movie.objects.none()
        return (
            Movie.objects.published()
            .filter(Q(title__icontains=q) | Q(original_title__icontains=q))
            .distinct()
            .with_card_data()
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q")
        context["title"] = f"'{context['q']}' bo'yicha qidiruv natijalari"
        return context


@login_required
@require_POST
@ratelimit(key=user_or_ip_key, rate=rate, group="watch_progress", method="POST", block=True)
def save_watch_progress(request, episode_id):
    """Pleyer pozitsiyasini saqlaydi (P1-T3).

    Pleyer har 10-15s POST yuboradi (client-side throttle): position_seconds,
    duration_seconds, completed (ixtiyoriy). 90%+ ko'rilgan bo'lsa avto-completed.
    """
    from users.models import WatchProgress

    from .models import Episode

    episode = get_object_or_404(Episode, id=episode_id)
    try:
        position = int(request.POST.get("position_seconds", 0))
        duration = int(request.POST.get("duration_seconds", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Noto'g'ri qiymat"}, status=400)

    completed = request.POST.get("completed") in ("1", "true", "True")
    if duration and position / duration >= 0.9:
        completed = True

    WatchProgress.objects.update_or_create(
        user=request.user,
        episode=episode,
        defaults={
            "position_seconds": max(position, 0),
            "duration_seconds": max(duration, 0),
            "completed": completed,
        },
    )
    return JsonResponse({"status": "saved", "completed": completed})
