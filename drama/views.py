# views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView
from django.views.generic.base import View
from django_ratelimit.decorators import ratelimit

from core.ratelimit import ip_key, rate, user_or_ip_key
from users.models import CoinTransaction, Notification, UserBlock, UserMovieList
from users.services import notifications as notif
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
    ReviewReaction,
    ReviewReport,
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


class HxPartialListMixin:
    """Cheksiz skroll [P5-T3] — htmx so'rovda faqat kartalar+sentinel partial'i.

    To'liq sahifa (oddiy GET) -> view'ning o'z template_name'i (base.html bilan).
    htmx so'rovi (skrollda keyingi sahifa YOKI explore filtr/sort almashuvi) ->
    _movie_items.html: kartalar + keyingi-sahifa sentineli, base.html'siz. Sentinel
    JS-siz oddiy <a href="?page=N"> bo'lgani uchun progressive enhancement saqlanadi.
    """

    hx_partial_template = "movies/partials/_movie_items.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return [self.hx_partial_template]
        return super().get_template_names()


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
        # FTS+trigram (postgres) — prefix-tsquery yozish asnosida ham topadi [P8-T1]
        from drama.services import search as search_service

        movies = search_service.search_movies(Movie.objects.published(), query)[:5]

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
class MoviesView(HxPartialListMixin, GenreYearMixin, ListView):
    model = Movie
    # [P9-T2] Karta faqat poster/title/yil/davlat/qism-soni ko'rsatadi:
    # select_related(category) + prefetch(genres, tags) ISHLATILMAY turib
    # har sahifada 2 ta bekor so'rov qo'shayotgan edi — olib tashlandi.
    queryset = Movie.objects.published().with_card_data().order_by("-id")
    template_name = "index.html"  # MANA SHU YERNI O'ZGARTIRING
    context_object_name = "movies"
    paginate_by = 12

    def get_context_data(self, **kwargs):
        from drama import recommendations

        context = super().get_context_data(**kwargs)
        context["top_sliders"] = TopSlider.objects.all()
        # Trenddagi karusel — keshdan (recompute_trending_movies to'ldiradi) [P8-T2]
        context["trending_movies"] = recommendations.trending_movies()
        # 'Davom ettirish' + 'siz ko'rganingiz asosida' — faqat kirgan foydalanuvchi
        if self.request.user.is_authenticated:
            from users.selectors import continue_watching

            context["continue_watching"] = continue_watching(self.request.user)
            context["recommended_movies"] = recommendations.because_you_watched(self.request.user)
        return context


@ratelimit(key=user_or_ip_key, rate=rate, group="report", method="POST", block=True)
def report_review(request, pk):
    """Izoh ustidan shikoyat — moderatsiya navbatiga tushadi [P14-T3].

    Dedup: (review, reporter) unique — takror POST yangi yozuv ochmaydi.
    Filtr: AUTO_HIDE_THRESHOLD ta ochiq shikoyat yig'ilsa izoh admin
    kutilmasdan avto-yashiriladi (admin rad etsa qayta ochiladi).
    """
    if request.method != "POST":
        return redirect("/")
    if not request.user.is_authenticated:
        return HttpResponse("Ruxsat berilmagan", status=401)

    review = get_object_or_404(Review.objects.select_related("movie"), pk=pk)
    reason = request.POST.get("reason", "")
    if reason not in ReviewReport.Reason.values:
        reason = ReviewReport.Reason.OTHER

    report, created = ReviewReport.objects.get_or_create(
        review=review, reporter=request.user, defaults={"reason": reason}
    )
    if created:
        pending = review.reports.filter(status=ReviewReport.Status.PENDING).count()
        if not review.is_hidden and pending >= ReviewReport.AUTO_HIDE_THRESHOLD:
            review.is_hidden = True
            review.save(update_fields=["is_hidden"])

    if request.headers.get("HX-Request"):
        return render(request, "movies/partials/_report_done.html", {"already": not created})

    if created:
        messages.success(request, "Shikoyat yuborildi — moderatorlar ko'rib chiqadi.")
    else:
        messages.info(request, "Siz bu izohga allaqachon shikoyat yuborgansiz.")
    return redirect(review.movie.get_absolute_url())


# drama/views.py
class TagDetailView(HxPartialListMixin, GenreYearMixin, ListView):
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


class GenreDetailView(HxPartialListMixin, GenreYearMixin, ListView):
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
    template_name = "movies/movie_detail.html"  # reels (vertikal) — tarixiy default
    context_object_name = "movie"

    def get_template_names(self):
        """Pleyer tanlovi Category.player_type orqali [klassik-pleyer].

        Nomga solishtirish EMAS (Category.name modeltranslation'da — til
        almashsa buzilardi). Kategoriyasiz kino bugungidek reels'da qoladi:
        klassik sahifa kategoriya orqali ONGLI yoqiladi.
        """
        category = self.object.category
        if category and category.player_type == Category.PlayerType.CLASSIC:
            return ["movies/movie_detail_classic.html"]
        return [self.template_name]

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
                Prefetch("reviews", queryset=self._reviews_queryset().order_by("-id"))
            )
        )

    def _reviews_queryset(self):
        """Root izohlar + replies prefetch; [V2B-T2] user_liked Exists subquery
        bilan (alohida so'rov YO'Q — like holati asosiy so'rov ichida keladi)."""
        roots = Review.objects.filter(parent=None, is_hidden=False).select_related(
            "user", "user__profile", "episode"
        )
        replies = (
            Review.objects.filter(is_hidden=False).select_related("user", "episode").order_by("id")
        )
        if self.request.user.is_authenticated:
            liked = Exists(
                ReviewReaction.objects.filter(review=OuterRef("pk"), user=self.request.user)
            )
            roots = roots.annotate(user_liked=liked)
            replies = replies.annotate(user_liked=liked)
        return roots.prefetch_related(Prefetch("replies", queryset=replies))

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

        # [V2B-T3] Sheet default ro'yxati: shu qism izohlari + umumiy (episode=null,
        # eski izohlar). Prefetch keshidan Python'da tanlanadi — qo'shimcha so'rov YO'Q.
        _roots = list(movie.reviews.all())
        if active_episode:
            context["sheet_reviews"] = [
                r for r in _roots if r.episode_id is None or r.episode_id == active_episode.id
            ]
        else:
            context["sheet_reviews"] = _roots

        # [V2E-T1] Aktiv qism subtitrlari — pleyerda <track> bo'ladi (1 so'rov)
        context["subtitles"] = list(active_episode.subtitles.all()) if active_episode else []

        # [V2B-T5] Bloklangan mualliflar izohlari collapse ko'rinadi
        from users.selectors import blocked_user_ids

        context["blocked_user_ids"] = blocked_user_ids(self.request.user)

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

        # O'xshash kinolar — teg+janr mosligi, per-kino versiyalangan keshda
        # (ID'lar keshda, obyektlar arzon pk-so'rovda) [P8-T2 / P9-T1]
        from drama import recommendations

        context["similar_movies"] = recommendations.similar_movies(movie)

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

        # 2. Asosiy izohlar (parent=None); [P9-T2] avatar + replies prefetch — N+1 yo'q
        replies = Review.objects.filter(is_hidden=False).select_related("user").order_by("id")
        qs = Review.objects.filter(movie=self.movie, parent=None, is_hidden=False).select_related(
            "user", "user__profile"
        )
        if self.request.user.is_authenticated:
            # [V2B-T2] foydalanuvchi reaksiyalari — Exists subquery (alohida so'rov YO'Q)
            liked = Exists(
                ReviewReaction.objects.filter(review=OuterRef("pk"), user=self.request.user)
            )
            qs = qs.annotate(user_liked=liked)
            replies = replies.annotate(user_liked=liked)
        qs = qs.prefetch_related(Prefetch("replies", queryset=replies))
        # [V2B-T2] saralash oq ro'yxati: top = Eng foydali (like_count), default = Yangi
        if self.request.GET.get("sort") == "top":
            return qs.order_by("-like_count", "-id")
        return qs.order_by("-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Template'da kino rasmi va nomini chiqarish uchun 'movie' ni context'ga uzatamiz
        context["movie"] = self.movie
        context["title"] = f"{self.movie.title} - Barcha fikrlar"
        # [V2B-T2] saralash holati (template tugmalari uchun; oq ro'yxat: new|top)
        context["sort"] = "top" if self.request.GET.get("sort") == "top" else "new"
        # [V2B-T5] blok collapse-filtri
        from users.selectors import blocked_user_ids

        context["blocked_user_ids"] = blocked_user_ids(self.request.user)
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
            # [V2B-T3] Ixtiyoriy qism-belgisi — qism SHU kinoniki bo'lishi shart
            episode_id = request.POST.get("episode")
            if episode_id:
                from .models import Episode

                try:
                    review.episode = Episode.objects.get(id=int(episode_id), movie=movie)
                except (ValueError, Episode.DoesNotExist):
                    return HttpResponse("Qism topilmadi", status=404)
            parent_id = request.POST.get("parent")
            is_reply = False
            parent = None
            if parent_id:
                # [V2B-T1] Har qanday authenticated user javob yoza oladi (ilgari
                # faqat superuser 403 bilan). Parent SHU kinoniki va yashirilmagan
                # bo'lishi shart; chuqurlik 1 — reply'ga reply thread ROOT'iga
                # bog'lanadi (UI reply-tugmani faqat rootda ko'rsatadi, bu server
                # tomonidagi himoya).
                try:
                    parent = Review.objects.select_related("user", "parent__user").get(
                        id=int(parent_id), movie=movie, is_hidden=False
                    )
                except (ValueError, Review.DoesNotExist):
                    return HttpResponse("Izoh topilmadi", status=404)
                if parent.parent_id:
                    parent = parent.parent
                # [V2B-T5] Blocker bloklagan muallifga javob yoza olmaydi
                if (
                    parent.user_id
                    and UserBlock.objects.filter(
                        blocker=request.user.profile, blocked__user_id=parent.user_id
                    ).exists()
                ):
                    return HttpResponse(
                        "Bloklangan foydalanuvchiga javob yozib bo'lmaydi", status=403
                    )
                review.parent = parent
                # [V2B-T3] Javob threadi bir joyda tursin — qism ROOT'dan meros
                review.episode = parent.episode
                is_reply = True
            review.save()
            if parent is not None and parent.user_id and parent.user_id != request.user.id:
                # Root-izoh muallifiga sayt-ichki bildirishnoma (o'ziga-o'zi javobda
                # EMAS; user=None — GDPR-anonimlangan izoh — ham o'tkazib yuboriladi)
                notif.notify(
                    parent.user,
                    Notification.Kind.REPLY,
                    f"{request.user.username} izohingizga javob berdi",
                    body=review.text[:200],
                    url=f"{reverse('drama:movie_reviews', args=[movie.slug])}#review-{parent.id}",
                )
            if request.headers.get("HX-Request"):
                return render(
                    request,
                    "movies/partials/comment_item.html",
                    {"review": review, "is_reply": is_reply},
                )
        return redirect(movie.get_absolute_url())


class ToggleReviewLike(View):
    """Izoh like toggle [V2B-T2] — idempotent: birinchi POST qo'shadi, ikkinchisi qaytaradi.

    create+IntegrityError (get_or_create EMAS): parallel ikki like'da unique
    constraint bittasini DB darajasida to'xtatadi — TOCTOU oynasi yo'q.
    like_count faqat F() bilan yangilanadi (race'da ham to'g'ri qoladi).
    """

    def post(self, request, pk):
        if not request.user.is_authenticated:
            return HttpResponse("Ruxsat berilmagan", status=401)
        review = get_object_or_404(Review.objects.select_related("movie"), pk=pk, is_hidden=False)
        try:
            with transaction.atomic():
                ReviewReaction.objects.create(user=request.user, review=review)
                Review.objects.filter(pk=pk).update(like_count=F("like_count") + 1)
            review.user_liked = True
        except IntegrityError:
            ReviewReaction.objects.filter(user=request.user, review=review).delete()
            Review.objects.filter(pk=pk, like_count__gt=0).update(like_count=F("like_count") - 1)
            review.user_liked = False
        review.refresh_from_db(fields=["like_count"])
        if request.headers.get("HX-Request"):
            return render(request, "movies/partials/_like_button.html", {"review": review})
        return redirect(review.movie.get_absolute_url())


class MovieCommentsPartial(View):
    """[V2B-T3] Izohlar ro'yxati fragmenti (HTMX toggle uchun).

    `?episode=<id>` — shu qism muhokamasi + UMUMIY (episode=null) izohlar
    (aks holda barcha eski izohlar qism-rejimda ko'rinmay qolardi);
    parametrsiz — kinoning hamma izohlari.
    """

    def get(self, request, pk):
        from .models import Episode

        movie = get_object_or_404(Movie.objects.published(), id=pk)
        replies = (
            Review.objects.filter(is_hidden=False).select_related("user", "episode").order_by("id")
        )
        roots = Review.objects.filter(movie=movie, parent=None, is_hidden=False).select_related(
            "user", "user__profile", "episode"
        )
        episode_id = request.GET.get("episode")
        if episode_id:
            try:
                episode = Episode.objects.get(id=int(episode_id), movie=movie)
            except (ValueError, Episode.DoesNotExist):
                return HttpResponse("Qism topilmadi", status=404)
            roots = roots.filter(Q(episode=episode) | Q(episode__isnull=True))
        if request.user.is_authenticated:
            liked = Exists(ReviewReaction.objects.filter(review=OuterRef("pk"), user=request.user))
            roots = roots.annotate(user_liked=liked)
            replies = replies.annotate(user_liked=liked)
        roots = roots.prefetch_related(Prefetch("replies", queryset=replies))
        from users.selectors import blocked_user_ids

        return render(
            request,
            "movies/partials/comment_list.html",
            {
                "reviews": roots.order_by("-id")[:30],
                "blocked_user_ids": blocked_user_ids(request.user),
            },
        )


# drama/views.py


class FilterMoviesView(HxPartialListMixin, GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12

    # Saralash oq ro'yxati [P8-T3] — foydalanuvchi kiritmasi order_by'ga
    # to'g'ridan-to'g'ri tushmaydi (injection yo'q). Kalit -> (order_by, yorliq).
    SORT_OPTIONS = {
        "new": (("-created_at",), "Yangi"),
        "rating": (("-mdl_rank", "-average_rating"), "Reyting"),
        "popular": (("-total_votes", "-average_rating"), "Mashhur"),
    }
    DEFAULT_SORT = "new"

    # get_template_names -> HxPartialListMixin (HX'da _movie_items.html) [P5-T3]

    def _current_sort(self) -> str:
        sort = self.request.GET.get("sort", self.DEFAULT_SORT)
        return sort if sort in self.SORT_OPTIONS else self.DEFAULT_SORT

    def get_queryset(self):
        # Parametrlarni olish
        year = self.request.GET.getlist("year")
        genre = self.request.GET.getlist("genre")
        country = self.request.GET.get("country")
        min_rating = self.request.GET.get("min_rating")

        # [P9-T2] Karta kategoriya/janr ko'rsatmaydi — select/prefetch bekor edi;
        # with_card_data() qism-soni annotatsiyasini beradi.
        queryset = Movie.objects.published().with_card_data()

        # Filtrlar mantiqi
        if year:
            queryset = queryset.filter(year__in=year)
        if genre:
            queryset = queryset.filter(genres__slug__in=genre)
        if country:
            queryset = queryset.filter(country=country)
        if min_rating:
            try:
                queryset = queryset.filter(mdl_rank__gte=float(min_rating))
            except (TypeError, ValueError):
                pass  # yaroqsiz reyting — e'tiborsiz

        order_by = self.SORT_OPTIONS[self._current_sort()][0]
        return queryset.distinct().order_by(*order_by)

    def get_context_data(self, **kwargs):
        from drama import facets

        context = super().get_context_data(**kwargs)
        # Faceted sonlar (keshlangan, catalog_ver bilan yangilanadi) [P8-T3]
        context["genre_facets"] = facets.genre_facets()
        context["country_facets"] = facets.country_facets()
        context["year_facets"] = facets.year_facets()
        # Saralash holati (UI faol variantni belgilashi + HTMX formada saqlash)
        context["sort_options"] = self.SORT_OPTIONS
        context["current_sort"] = self._current_sort()
        # Tanlangan filtrlarni saqlash (HTMX qayta so'rovda checkbox holati)
        context["selected_years"] = self.request.GET.getlist("year")
        context["selected_genres"] = self.request.GET.getlist("genre")
        context["selected_country"] = self.request.GET.get("country", "")
        context["selected_min_rating"] = self.request.GET.get("min_rating", "0")
        return context


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


class Search(HxPartialListMixin, GenreYearMixin, ListView):
    template_name = "movies/explore_list.html"
    context_object_name = "movies"
    paginate_by = 12

    def get_queryset(self):
        # FTS+trigram [P8-T1]: relevantlik tartibi servisdan keladi —
        # bu yerda qo'shimcha order_by QO'YILMAYDI (rank buzilardi).
        from drama.services import search as search_service

        q = self.request.GET.get("q", "").strip()
        return search_service.search_movies(Movie.objects.published().with_card_data(), q)

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
    if completed:
        _queue_next_episode(request.user, episode)
    return JsonResponse({"status": "saved", "completed": completed})


def _queue_next_episode(user, episode):
    """Smart continue: qism tugatilgach KEYINGI ko'rilmagan qism 'davom ettirish'ga
    0% qator bo'lib tushadi (users.selectors.continue_watching uni kinoning eng
    so'nggi harakati sifatida ko'rsatadi). Tugatilgan keyingi qismlar sakraladi —
    rewatch'da birinchi KO'RILMAGANI navbatga tushadi. get_or_create: chala
    ko'rilgan qism progressi hech qachon ustiga yozilmaydi. Keyingi qism bo'lmasa
    (serial oxiri) — jim; yangi qism chiqqanda V2A-T1 obuna fan-out xabar beradi.
    """
    from users.models import WatchProgress

    from .models import Episode

    next_ep = (
        Episode.objects.filter(movie_id=episode.movie_id, episode_number__gt=episode.episode_number)
        .exclude(watch_progress__user=user, watch_progress__completed=True)
        .order_by("episode_number")
        .first()
    )
    if next_ep is not None:
        WatchProgress.objects.get_or_create(user=user, episode=next_ep)
