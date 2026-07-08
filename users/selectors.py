"""users/selectors.py — o'qish so'rovlari (yagona manba) [P6-T3]."""

from __future__ import annotations

from users.models import WatchProgress


def continue_watching(user, limit: int = 12):
    """'Davom ettirish': tugatilmagan progresslar, eng so'nggi birinchi.

    Bosh sahifa (drama.views.MoviesView) va kabinet (profil) SHU yagona so'rovni
    ishlatadi — mantiq bir joyda (completed=False + N+1'siz select_related).
    """
    return (
        WatchProgress.objects.filter(user=user, completed=False)
        .select_related("episode", "episode__movie")
        .order_by("-updated_at")[:limit]
    )
