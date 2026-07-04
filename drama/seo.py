"""drama/seo.py — JSON-LD structured data builder [P5-T4].

JSON shablon ichida qo'lda yasalmaydi: sarlavhadagi qo'shtirnoq JSONni buzar
yoki autoescape uni &quot; ga aylantirib yuborar edi. Bu yerda json.dumps +
'<' escape (script-breakout himoyasi) bilan xavfsiz quriladi va sof funksiya
sifatida testlanadi.
"""

import json

from django.urls import reverse
from django.utils.safestring import mark_safe


def to_jsonld(data: dict) -> str:
    """XSS-xavfsiz JSON-LD matni ('<' -> \\u003c: </script> breakout yopiq)."""
    return mark_safe(json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))


def movie_jsonld(request, movie, active_episode=None) -> str:
    """Kino sahifasi grafi: TVSeries/Movie + TVEpisode + VideoObject + BreadcrumbList.

    Serial (epizodli) -> TVSeries + aktiv qism TVEpisode; yakka film -> Movie.
    VideoObject faqat haqiqiy video manba bor bo'lganda chiqadi (Google talabi:
    uploadDate + thumbnail; embedUrl sifatida tomosha sahifasi).
    """
    url = request.build_absolute_uri(movie.get_absolute_url())
    poster = movie.poster.url if movie.poster else ""
    if poster.startswith("/"):
        poster = request.build_absolute_uri(poster)

    episode_count = movie.episodes.count()
    is_series = episode_count > 0

    main: dict = {
        "@type": "TVSeries" if is_series else "Movie",
        "name": movie.title,
        "url": url,
    }
    if movie.description:
        main["description"] = movie.description[:300]
    if poster:
        main["image"] = poster
    if movie.year:
        main["datePublished"] = f"{movie.year}-01-01"
    if is_series:
        main["numberOfEpisodes"] = episode_count
    genres = [genre.name for genre in movie.genres.all()]
    if genres:
        main["genre"] = genres

    graph: list[dict] = [main]

    if active_episode is not None:
        ep_url = f"{url}?episode={active_episode.episode_number}"
        episode: dict = {
            "@type": "TVEpisode",
            "name": f"{movie.title} — {active_episode.episode_number}-qism",
            "episodeNumber": active_episode.episode_number,
            "url": ep_url,
            "partOfSeries": {"@type": "TVSeries", "name": movie.title, "url": url},
        }
        if active_episode.season_id:
            episode["partOfSeason"] = {
                "@type": "TVSeason",
                "seasonNumber": active_episode.season.number,
            }
        graph.append(episode)

        if active_episode.bunny_video_id or active_episode.video_embed_code:
            graph.append(
                _video_object(
                    name=f"{movie.title} {active_episode.episode_number}-qism (o'zbek tilida)",
                    description=(movie.description or movie.title)[:300],
                    embed_url=ep_url,
                    upload_date=active_episode.created_at.date().isoformat(),
                    poster=poster,
                )
            )
    elif movie.bunny_video_id or movie.film_embed_code:
        # Yakka film — video Movie'ning o'zida
        graph.append(
            _video_object(
                name=f"{movie.title} (o'zbek tilida)",
                description=(movie.description or movie.title)[:300],
                embed_url=url,
                upload_date=movie.created_at.date().isoformat(),
                poster=poster,
            )
        )

    graph.append(
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Bosh sahifa",
                    "item": request.build_absolute_uri("/"),
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Katalog",
                    "item": request.build_absolute_uri(reverse("drama:explore")),
                },
                {"@type": "ListItem", "position": 3, "name": movie.title, "item": url},
            ],
        }
    )

    return to_jsonld({"@context": "https://schema.org", "@graph": graph})


def _video_object(
    name: str, description: str, embed_url: str, upload_date: str, poster: str
) -> dict:
    video: dict = {
        "@type": "VideoObject",
        "name": name,
        "description": description,
        "embedUrl": embed_url,
        "uploadDate": upload_date,
    }
    if poster:
        # Bunny thumbnail endi token-muddatli [P4-T1] — Google keshiga yaroqsiz;
        # poster (ochiq CDN) ishlatiladi.
        video["thumbnailUrl"] = poster
    return video
