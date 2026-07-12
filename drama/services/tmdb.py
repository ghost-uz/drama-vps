"""drama/services/tmdb.py — TMDB metadata import [V2D-T1].

Admin "TMDB'dan import" sahifasi uchun ikki bosqichli oqim:
  1. SINXRON (admin request ichida, ~0.5s): qidiruv/fetch_details + Movie/
     Genre/Actor yozuvlari — xato bo'lsa admin DARHOL tushunarli xabar
     ko'radi [AC-4], yangi qoralama darhol ochiladi.
  2. FON (Celery, drama.tasks.tmdb_download_images): poster va aktyor
     rasmlarini yuklab olish — sekin qism adminni bloklamaydi (retry bilan).

Auth: TMDB_API_KEY v3 kalit (api_key param) yoki v4 Read Access Token
("eyJ..." — Bearer header); ikkalasi ham qabul qilinadi.
Poster/rasm huquqlari eslatmasi: docs/ops/tmdb-import.md.
"""

from __future__ import annotations

import logging
import re
from functools import partial

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import translation
from django.utils.text import slugify

logger = logging.getLogger(__name__)

_BASE = "https://api.themoviedb.org/3"
_IMAGE_BASE = "https://image.tmdb.org/t/p"
_TIMEOUT = 15
_IMAGE_TIMEOUT = 30

MAX_ACTORS = 10  # credits.cast'dan olinadigan aktyorlar soni
MAX_MAIN_ACTORS = 5  # birinchilari main_actors'ga ham kiradi

# TMDB janr ID -> lokal Genre nomi (uz) [AC: janr mapping jadvali].
# Ro'yxatda yo'q ID import'da O'TKAZIB YUBORILADI (INFO log bilan).
TMDB_GENRE_MAP = {
    # umumiy (movie + tv)
    16: "Animatsiya",
    18: "Drama",
    35: "Komediya",
    37: "Vestern",
    80: "Jinoyat",
    99: "Hujjatli",
    9648: "Sirli",
    10751: "Oilaviy",
    # movie
    12: "Sarguzasht",
    14: "Fantastika",
    27: "Qo'rqinchli",
    28: "Jangari",
    36: "Tarixiy",
    53: "Triller",
    878: "Ilmiy-fantastika",
    10402: "Musiqiy",
    10749: "Romantika",
    10752: "Harbiy",
    10770: "TV film",
    # tv
    10759: "Jangari va sarguzasht",
    10762: "Bolalar",
    10763: "Yangiliklar",
    10764: "Realiti-shou",
    10765: "Ilmiy-fantastika va fantastika",
    10766: "Melodrama",
    10767: "Tok-shou",
    10768: "Urush va siyosat",
}

# ISO 3166-1 -> lokal davlat nomi: explore filtridagi distinct country
# ro'yxati izchil qolsin [P9-T2]. Yo'q kod — kodning o'zi yoziladi.
COUNTRY_MAP = {
    "KR": "Janubiy Koreya",
    "JP": "Yaponiya",
    "CN": "Xitoy",
    "TW": "Tayvan",
    "HK": "Gonkong",
    "TH": "Tailand",
    "PH": "Filippin",
    "VN": "Vyetnam",
    "IN": "Hindiston",
    "TR": "Turkiya",
    "US": "AQSH",
    "GB": "Buyuk Britaniya",
    "FR": "Fransiya",
    "RU": "Rossiya",
    "UZ": "O'zbekiston",
    "SG": "Singapur",
}

_GENDER_MAP = {1: "female", 2: "male"}  # TMDB gender kodi -> Actor.GENDER_CHOICES

_URL_RE = re.compile(r"themoviedb\.org/(tv|movie)/(\d+)")
_REF_RE = re.compile(r"^(tv|movie)\s*[/:]\s*(\d+)$")


class TmdbError(Exception):
    """Admin'ga to'g'ridan ko'rsatiladigan tushunarli xato [AC-4]."""


# --- API qatlami ---


def _request(path: str, params: dict | None = None) -> dict:
    """TMDB API GET; HTTP/tarmoq muammolari tushunarli TmdbError bo'ladi."""
    key = settings.TMDB_API_KEY
    if not key:
        raise TmdbError("TMDB_API_KEY sozlanmagan — .env faylini to'ldiring.")
    params = dict(params or {})
    headers = {"accept": "application/json"}
    if key.startswith("eyJ"):  # v4 Read Access Token (JWT)
        headers["Authorization"] = f"Bearer {key}"
    else:  # v3 kalit
        params["api_key"] = key
    try:
        resp = requests.get(f"{_BASE}{path}", params=params, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise TmdbError(f"TMDB'ga ulanib bo'lmadi: {exc}") from exc
    if resp.status_code == 401:
        raise TmdbError("TMDB API kaliti noto'g'ri (401).")
    if resp.status_code == 404:
        raise TmdbError("TMDB'da bunday yozuv topilmadi (404).")
    if resp.status_code == 429:
        raise TmdbError("TMDB so'rov chegarasi (429) — birozdan keyin urinib ko'ring.")
    if resp.status_code != 200:
        raise TmdbError(f"TMDB xatosi: HTTP {resp.status_code}.")
    return resp.json()


def download_image(path: str, size: str = "original") -> bytes:
    """TMDB rasm CDN'idan baytlar.

    requests xatolari ATAYIN xom qoladi (TmdbError'ga o'ralmaydi) —
    tmdb_download_images Celery task'i ular bo'yicha retry qiladi.
    """
    resp = requests.get(f"{_IMAGE_BASE}/{size}{path}", timeout=_IMAGE_TIMEOUT)
    resp.raise_for_status()
    return resp.content


# --- Kirish talqini va qidiruv ---


def parse_ref(text: str, default_type: str = "tv") -> tuple[str, int]:
    """'1396' / 'tv/1396' / themoviedb.org URL -> (media_type, id).

    Sof raqam default_type ID'si deb olinadi; talqin qilib bo'lmasa TmdbError.
    """
    text = (text or "").strip()
    m = _URL_RE.search(text) or _REF_RE.match(text)
    if m is not None:
        return m.group(1), int(m.group(2))
    if text.isdigit():
        return (default_type if default_type in ("tv", "movie") else "tv"), int(text)
    raise TmdbError(
        "TMDB manzili tushunarsiz — raqamli ID (1396), 'tv/1396' yoki "
        "themoviedb.org havolasini kiriting."
    )


def search(query: str, media_type: str = "tv") -> list[dict]:
    """Nom bo'yicha qidiruv — admin sahifadagi natijalar ro'yxati."""
    data = _request(f"/search/{media_type}", {"query": query, "language": settings.TMDB_LANGUAGE})
    results = []
    for item in (data.get("results") or [])[:10]:
        results.append(
            {
                "tmdb_ref": f"{media_type}/{item['id']}",
                "title": item.get("name") or item.get("title") or "",
                "original_title": item.get("original_name") or item.get("original_title") or "",
                "year": _year(item.get("first_air_date") or item.get("release_date")),
                "overview": (item.get("overview") or "")[:220],
                "poster_url": (
                    f"{_IMAGE_BASE}/w92{item['poster_path']}" if item.get("poster_path") else ""
                ),
            }
        )
    return results


def search_or_lookup(query: str, media_type: str = "tv") -> list[dict]:
    """Qidiruv qutisi semantikasi: ID/URL -> bitta aniq yozuv, matn -> qidiruv.

    Sof raqam avval ID deb sinaladi; ID topilmasa (404) matn-qidiruvga
    qaytiladi — «1923» kabi raqam-nomli seriallar ham yo'qolmaydi.
    """
    try:
        ref_type, ref_id = parse_ref(query, default_type=media_type)
    except TmdbError:
        return search(query, media_type)
    try:
        d = fetch_details(ref_type, ref_id)
    except TmdbError:
        if query.strip().isdigit():
            return search(query, media_type)
        raise
    return [
        {
            "tmdb_ref": d["tmdb_ref"],
            "title": d["title"],
            "original_title": d["original_title"],
            "year": d["year"],
            "overview": d["description"][:220],
            "poster_url": f"{_IMAGE_BASE}/w92{d['poster_path']}" if d["poster_path"] else "",
        }
    ]


# --- Normalizatsiya ---


def fetch_details(media_type: str, tmdb_id: int) -> dict:
    """Bitta TMDB yozuvini (credits bilan) model-maydonlarga normalizatsiya qiladi."""
    data = _request(
        f"/{media_type}/{tmdb_id}",
        {"language": settings.TMDB_LANGUAGE, "append_to_response": "credits"},
    )
    is_tv = media_type == "tv"
    countries = list(data.get("origin_country") or []) or [
        c.get("iso_3166_1", "") for c in data.get("production_countries") or []
    ]
    runtime = (data.get("episode_run_time") or [0])[0] if is_tv else (data.get("runtime") or 0)
    cast = ((data.get("credits") or {}).get("cast") or [])[:MAX_ACTORS]
    return {
        "tmdb_ref": f"{media_type}/{tmdb_id}",
        "title": (data.get("name") if is_tv else data.get("title")) or "",
        "original_title": (
            (data.get("original_name") if is_tv else data.get("original_title")) or ""
        ),
        "description": data.get("overview") or "",
        "tagline": data.get("tagline") or "",
        "year": _year(data.get("first_air_date") if is_tv else data.get("release_date")),
        "country": COUNTRY_MAP.get(countries[0], countries[0]) if countries else "",
        "duration": runtime,
        "episodes_count": (data.get("number_of_episodes") or 1) if is_tv else 1,
        "genre_ids": [g["id"] for g in data.get("genres") or []],
        "poster_path": data.get("poster_path") or "",
        "cast": [
            {
                "tmdb_person_id": c.get("id", 0),
                "name": c.get("name") or "",
                "original_name": c.get("original_name") or "",
                "gender": _GENDER_MAP.get(c.get("gender"), "male"),
                "profile_path": c.get("profile_path") or "",
            }
            for c in cast
            if c.get("name")
        ],
    }


def _year(date_str: str | None) -> int | None:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


# --- Import ---


def import_movie(media_type: str, tmdb_id: int):
    """TMDB yozuvidan draft Movie yaratadi [AC-1]; rasmlarni Celery'ga beradi.

    Dublikat (tmdb_id unique [AC-2]) va API xatolari -> TmdbError.
    """
    from drama.models import Movie
    from drama.tasks import tmdb_download_images

    ref = f"{media_type}/{tmdb_id}"
    existing = Movie.objects.filter(tmdb_id=ref).first()
    if existing is not None:
        raise TmdbError(
            f"Bu TMDB yozuvi allaqachon import qilingan: «{existing.title}» (id={existing.pk})."
        )

    details = fetch_details(media_type, tmdb_id)
    title = details["title"] or details["original_title"]
    if not title:
        raise TmdbError("TMDB javobida nom yo'q — import to'xtatildi.")

    # Import DOIM sayt default tilida yoziladi (admin UI tili ta'sir qilmasin):
    # modeltranslation title/description/tagline'ni faol til ustuniga yozadi.
    with translation.override(settings.LANGUAGE_CODE), transaction.atomic():
        movie = Movie(
            title=title,
            original_title=details["original_title"],
            description=details["description"],
            tagline=details["tagline"],
            year=details["year"] or 2024,
            country=details["country"],
            duration=details["duration"] or 60,
            episodes_count=details["episodes_count"],
            # Playback invarianti: faqat published ko'rinadi — import qoralama [AC-1].
            status=Movie.Status.DRAFT,
            slug=_unique_slug(title, details),
            tmdb_id=ref,
        )
        movie.save()

        skipped = [g for g in details["genre_ids"] if g not in TMDB_GENRE_MAP]
        if skipped:
            logger.info("TMDB janr mapping'da yo'q, o'tkazildi: %s (%s)", skipped, ref)
        movie.genres.set(
            [
                _get_or_create_genre(TMDB_GENRE_MAP[g])
                for g in details["genre_ids"]
                if g in TMDB_GENRE_MAP
            ]
        )

        actors = [_get_or_create_actor(item) for item in details["cast"]]
        movie.actors.set(actors)
        movie.main_actors.set(actors[:MAX_MAIN_ACTORS])

        # Rasm yuklash — sekin qism: Celery'ga (admin bloklanmaydi).
        actor_paths = {
            actor.pk: item["profile_path"]
            for actor, item in zip(actors, details["cast"], strict=True)
            if item["profile_path"] and not actor.image
        }
        transaction.on_commit(
            partial(tmdb_download_images.delay, movie.pk, details["poster_path"], actor_paths)
        )
    return movie


def _unique_slug(title: str, details: dict) -> str:
    """slugify to'qnashuvida -yil suffiks [AC-2]; oxirgi chora — tmdb ref."""
    from drama.models import Movie

    ref_slug = details["tmdb_ref"].replace("/", "-")
    base = slugify(title) or slugify(details["original_title"]) or ref_slug
    slug = base
    if details["year"] and Movie.objects.filter(slug=slug).exists():
        slug = f"{base}-{details['year']}"
    if Movie.objects.filter(slug=slug).exists():
        slug = f"{base}-{ref_slug}"  # tmdb_id unique -> bu kafolatli unikal
    return slug[:160]


def _get_or_create_genre(name: str):
    """Slug — tildan mustaqil identifikator (name_uz bo'sh eski yozuvlar ham topilsin)."""
    from drama.models import Genre

    slug = slugify(name)
    genre = Genre.objects.filter(Q(name=name) | Q(slug=slug)).first()
    if genre is None:
        genre = Genre.objects.create(name=name, slug=slug)
    return genre


def _get_or_create_actor(item: dict):
    """Dedup: original_name (native yozuv) bo'yicha, keyin name bo'yicha [AC-3]."""
    from drama.models import Actor

    lookup = item["original_name"] or item["name"]
    actor = Actor.objects.filter(Q(original_name=lookup) | Q(name=item["name"])).first()
    if actor is not None:
        return actor
    base = slugify(item["name"]) or f"tmdb-{item['tmdb_person_id']}"
    slug = base
    if Actor.objects.filter(slug=slug).exists():
        slug = f"{base}-{item['tmdb_person_id']}"  # bir xil ismli BOSHQA shaxs
    return Actor.objects.create(
        name=item["name"],
        original_name=item["original_name"],
        gender=item["gender"],
        slug=slug,
    )
