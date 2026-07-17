"""users/selectors.py — o'qish so'rovlari (yagona manba) [P6-T3]."""

from __future__ import annotations

from django.db.models import F, Window
from django.db.models.functions import RowNumber

from users.models import WatchProgress


def continue_watching(user, limit: int = 12):
    """'Davom ettirish': tugatilmagan progresslar, eng so'nggi birinchi.

    Bosh sahifa (drama.views.MoviesView) va kabinet (profil) SHU yagona so'rovni
    ishlatadi — mantiq bir joyda (completed=False + N+1'siz select_related).
    Har kino/serialdan FAQAT eng so'nggi ko'rilgan qism chiqadi (ROW_NUMBER
    per-movie) — aks holda bitta serialning bir nechta chala qismi ro'yxatni
    bosib ketadi. pk tiebreak: updated_at teng bo'lsa ham deterministik.
    """
    return (
        WatchProgress.objects.filter(user=user, completed=False)
        .annotate(
            rn=Window(
                RowNumber(),
                partition_by=F("episode__movie_id"),
                order_by=[F("updated_at").desc(), F("pk").desc()],
            )
        )
        .filter(rn=1)
        .select_related("episode", "episode__movie")
        .order_by("-updated_at")[:limit]
    )
