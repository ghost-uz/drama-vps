"""drama/services/playback.py — video ko'rish ruxsati (gating) [P2-T4].

YAGONA MANBA: HTML view (movie_detail) ham, REST API (playback) ham shu
funksiyani chaqiradi -> gating qoidasi bitta joyda. Ikki joyda bo'lsa biri
yangilanganda ikkinchisi eskirib video sizib chiqishi mumkin edi.

Qoida: 1-10 qism tekin; 11+ -> funding bo'lsa has_access, VIP bo'lsa premium.
Superuser har doim ko'radi.
"""

FREE_EPISODE_LIMIT = 10

RESTRICTION_FUNDING = "funding"
RESTRICTION_VIP = "vip"


def get_episode_access(user, episode):
    """Foydalanuvchi epizodni ko'ra oladimi.

    Qaytaradi: (allowed: bool, restriction_type: str | None).
    """
    if episode.episode_number <= FREE_EPISODE_LIMIT:
        return True, None

    if user.is_authenticated and user.is_superuser:
        return True, None

    movie = episode.movie
    funding_project = getattr(movie, "funding_project", None)

    if funding_project:
        allowed = user.is_authenticated and funding_project.has_access(user.profile)
        return (True, None) if allowed else (False, RESTRICTION_FUNDING)

    if movie.is_vip:
        profile = getattr(user, "profile", None)
        is_premium = user.is_authenticated and getattr(profile, "is_currently_premium", False)
        return (True, None) if is_premium else (False, RESTRICTION_VIP)

    # 11+ qism, lekin serial VIP ham, funding ham emas -> tekin
    return True, None
