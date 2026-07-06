"""Tavsiya servisi [P8-T2] — o'xshash / trenddagi / "siz ko'rganingiz asosida".

Uch xil tavsiya, uch xil hisoblash-narxi egasi:
- ``trending_movies`` — BUTUN sayt uchun bir xil → Celery oldindan hisoblab
  keshlaydi (drama.tasks.recompute_trending_movies), bu yer keshdan o'qiydi;
- ``similar_movies`` — har kino uchun BARQAROR → per-kino versiyalangan kesh
  (P9-T1 catalog:v{n}); ID'lar keshda, obyektlar arzon pk-so'rovda (reyting/
  poster .update() bilan eskirmasin);
- ``because_you_watched`` — har FOYDALANUVCHIGA xos → keshlab bo'lmaydi, lekin
  kirish (oxirgi ko'rilganlar) cheklanadi → yengil qoladi.

Barcha funksiya ``list`` qaytaradi (queryset EMAS) — shablon/kesh uchun tayyor.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone

from drama.cache import get_or_set_catalog
from drama.models import Movie

# "Trenddagi" oynasi: shu kun ichidagi ko'rish faolligi sanaladi.
TRENDING_WINDOW_DAYS = 7
TRENDING_CACHE_KEY = "trending_movies"  # versiyalangan (catalog_key bilan o'raladi)


def _cards(ids: list[int]) -> list[Movie]:
    """ID ro'yxatini karta-tayyor Movie obyektlariga aylantiradi, tartibni saqlaydi.

    Kesh ID'larni saqlaydi, obyektlar HAR safar yangi olinadi — reyting/qism-soni/
    poster o'zgarsa kartada eskirmaydi (P9-T1 similar bilan bir xil yondashuv).
    """
    if not ids:
        return []
    by_id = {m.pk: m for m in Movie.objects.published().with_card_data().filter(id__in=ids)}
    return [by_id[i] for i in ids if i in by_id]


def compute_trending_ids(limit: int = 12) -> list[int]:
    """Trenddagi kino ID'lari — oxirgi hafta ko'rish faolligi bo'yicha [P8-T2].

    Faollik = shu oynadagi WatchProgress yozuvlari soni (episode->movie orqali).
    Yangi/kam-trafikli katalogda faollik bo'lmasligi mumkin → baho/ovoz bo'yicha
    to'ldiriladi (natija hech qachon bo'sh chiqmaydi). Celery task chaqiradi.
    """
    since = timezone.now() - timedelta(days=TRENDING_WINDOW_DAYS)
    # Yo'l: Movie -> episodes (Episode.movie — HAR DOIM to'ldirilgan; season
    # null bo'lishi mumkin, shuning uchun seasons__episodes ISHLATILMAYDI) ->
    # watch_progress. distinct=True — bir kinoda ko'p qism JOIN'i sonni buzmasin.
    active = list(
        Movie.objects.published()
        .annotate(
            recent_views=Count(
                "episodes__watch_progress",
                filter=Q(episodes__watch_progress__updated_at__gte=since),
                distinct=True,
            )
        )
        .filter(recent_views__gt=0)
        .order_by("-recent_views", "-average_rating", "-total_votes")
        .values_list("id", flat=True)[:limit]
    )
    if len(active) >= limit:
        return active

    # To'ldirish: eng yuqori baholangan/mashhur (allaqachon tanlanganlarni chiqarib).
    fill = list(
        Movie.objects.published()
        .exclude(id__in=active)
        .order_by("-average_rating", "-total_votes", "-created_at")
        .values_list("id", flat=True)[: limit - len(active)]
    )
    return active + fill


def trending_movies(limit: int = 12) -> list[Movie]:
    """Keshdan trenddagi kinolar (recompute_trending_movies task to'ldiradi)."""
    ids = get_or_set_catalog(TRENDING_CACHE_KEY, lambda: compute_trending_ids(limit))
    return _cards(ids[:limit])


def compute_similar_ids(movie: Movie, limit: int = 6) -> list[int]:
    """O'xshash kino ID'lari — teg VA janr mosligi bo'yicha [P8-T2].

    Eski mantiq FAQAT teg mosligini sanardi; endi janr ham qo'shildi
    (ko'p kinoda teg kam, janr esa doim bor) — moslik = mos teg + mos janr
    yig'indisi, keyin mdl_rank. Til-neytral (teg/janr tilга bog'liq emas).
    """
    tag_ids = list(movie.tags.values_list("id", flat=True))
    genre_ids = list(movie.genres.values_list("id", flat=True))
    if not tag_ids and not genre_ids:
        # Teg ham janr ham yo'q — o'sha davlatdagi yuqori reyting bilan to'ldiramiz
        return list(
            Movie.objects.published()
            .filter(country=movie.country)
            .exclude(id=movie.id)
            .order_by("-mdl_rank", "-average_rating")
            .values_list("id", flat=True)[:limit]
        )

    # Shart va "moslik" hisobini DINAMIK quramiz — bo'sh ``__in=[]`` (OR va
    # filtered-Count ichida noto'g'ri natija/EmptyResultSet beradi) hech qachon
    # tushmasin. Faqat mavjud (bo'sh bo'lmagan) ro'yxatlar qatnashadi.
    match_filter = Q()
    shared = None
    if tag_ids:
        match_filter |= Q(tags__in=tag_ids)
        shared = Count("tags", filter=Q(tags__in=tag_ids), distinct=True)
    if genre_ids:
        match_filter |= Q(genres__in=genre_ids)
        genre_count = Count("genres", filter=Q(genres__in=genre_ids), distinct=True)
        shared = genre_count if shared is None else shared + genre_count

    return list(
        Movie.objects.published()
        .filter(match_filter)
        .exclude(id=movie.id)
        .annotate(shared=shared)
        .order_by("-shared", "-mdl_rank")
        .values_list("id", flat=True)[:limit]
    )


def similar_movies(movie: Movie, limit: int = 6) -> list[Movie]:
    """Berilgan kinoga o'xshashlar — per-kino versiyalangan keshdan [P8-T2]."""
    ids = get_or_set_catalog(f"similar:{movie.pk}", lambda: compute_similar_ids(movie, limit))
    return _cards(ids[:limit])


def new_movies(limit: int = 12) -> list[Movie]:
    """Eng yangi chop etilgan kinolar (karusel uchun)."""
    return list(Movie.objects.published().with_card_data().order_by("-created_at")[:limit])


def because_you_watched(user: User, limit: int = 12) -> list[Movie]:
    """Foydalanuvchining ko'rish tarixiga asoslangan tavsiyalar [P8-T2].

    Kirish CHEKLANGAN (keshsiz, per-user — yengil bo'lishi shart): oxirgi ~15 ta
    ko'rilgan kino janrlari yig'iladi, o'sha janrdagi HALI KO'RILMAGAN kinolar
    janr-mosligi + reyting bo'yicha qaytariladi. Anonim yoki tarixsiz -> bo'sh.
    """
    if not user.is_authenticated:
        return []

    # Oxirgi ko'rilgan kinolar (episode->movie orqali; DISTINCT so'nggi 15)
    watched_movie_ids = list(
        Movie.objects.filter(episodes__watch_progress__user=user)
        .distinct()
        .order_by()  # distinct + slice uchun tartibsiz (tez)
        .values_list("id", flat=True)[:50]
    )
    if not watched_movie_ids:
        return []

    liked_genres = list(
        Movie.objects.filter(id__in=watched_movie_ids)
        .values_list("genres__id", flat=True)
        .distinct()
    )
    liked_genres = [g for g in liked_genres if g is not None]
    if not liked_genres:
        return []

    # Avval reytinglangan ID'lar (bitta Count annotatsiya), keyin _cards() —
    # with_card_data'ning episode-Count'i bilan bir so'rovda stacklamaymiz
    # (ikki M2M-Count o'zaro ko'paytma xatosi + ortiqcha DISTINCT'dan qochish).
    ids = list(
        Movie.objects.published()
        .filter(genres__in=liked_genres)
        .exclude(id__in=watched_movie_ids)  # allaqachon ko'rilganni tavsiya qilmaymiz
        .annotate(match=Count("genres", filter=Q(genres__in=liked_genres), distinct=True))
        .order_by("-match", "-average_rating", "-total_votes")
        .values_list("id", flat=True)[:limit]
    )
    return _cards(ids)
