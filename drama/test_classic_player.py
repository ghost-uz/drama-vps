"""Klassik pleyer testlari [klassik-pleyer] — Category.player_type bo'yicha
template tanlash, klassik sahifa render, VIP qulf, legacy reels saqlanishi."""

import pytest

from drama.factories import EpisodeFactory, MovieFactory
from drama.models import Category

pytestmark = pytest.mark.django_db


def _category(player_type):
    return Category.objects.create(
        name=f"Kat {player_type}", slug=f"kat-{player_type}", player_type=player_type
    )


def test_player_type_default_classic():
    # YANGI kategoriya default'i classic (migratsiya mavjudlarini reels qiladi)
    cat = Category.objects.create(name="Filmlar", slug="filmlar")
    assert cat.player_type == Category.PlayerType.CLASSIC


def test_uncategorized_stays_on_reels(client):
    # Kategoriyasiz (legacy) kontent BUGUNGIDEK reels'da — regressiya yo'q
    movie = MovieFactory()
    EpisodeFactory(movie=movie, episode_number=1)
    resp = client.get(movie.get_absolute_url())
    assert resp.status_code == 200
    assert "movies/movie_detail.html" in [t.name for t in resp.templates]
    assert b"reelsData" in resp.content


def test_reels_category_uses_reels_template(client):
    movie = MovieFactory(category=_category("reels"))
    EpisodeFactory(movie=movie, episode_number=1)
    resp = client.get(movie.get_absolute_url())
    assert "movies/movie_detail.html" in [t.name for t in resp.templates]
    assert b"reelsData" in resp.content


def test_classic_category_uses_classic_template(client):
    movie = MovieFactory(category=_category("classic"))
    EpisodeFactory(movie=movie, episode_number=1)
    EpisodeFactory(movie=movie, episode_number=2)
    resp = client.get(movie.get_absolute_url())
    assert resp.status_code == 200
    names = [t.name for t in resp.templates]
    assert "movies/movie_detail_classic.html" in names
    assert "movies/movie_detail.html" not in names
    html = resp.content.decode()
    assert "classicData" in html
    assert "reelsData" not in html
    # Qismlar to'ri: havolalar + aktiv qism belgisi
    assert "?episode=2" in html
    assert 'aria-current="true"' in html
    # Pleyer boshqaruvlari
    assert 'id="cpVideo"' in html
    assert 'id="cpControls"' in html


def test_classic_vip_lock_hides_video(client, monkeypatch):
    monkeypatch.setattr(
        "drama.services.playback.get_episode_access", lambda user, ep: (False, "vip")
    )
    movie = MovieFactory(category=_category("classic"), is_vip=True)
    EpisodeFactory(movie=movie, episode_number=1)
    resp = client.get(movie.get_absolute_url())
    html = resp.content.decode()
    # E2E bilan bir xil matnlar (test_flows VIP oqimi shunga tayanadi)
    assert "VIP Bo'lim" in html
    assert "premium obuna kerak" in html
    # Qulfda video element ham, imzoli URL ham sizmaydi
    assert 'id="cpVideo"' not in html
    assert "cp-lock" in html


def test_classic_film_without_episodes_renders(client):
    # Yakka film: epizod yo'q — movie-darajali video yo'li (active_episode None)
    movie = MovieFactory(category=_category("classic"))
    resp = client.get(movie.get_absolute_url())
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "classicData" in html
    assert '"episodeId": null' in html


def test_no_multiline_hash_comments_in_templates():
    """{# #} FAQAT bir qatorlik — ko'p qatorda davomi sahifaga MATN bo'lib chiqadi.

    Klassik sahifa base.html'dagi ana shunday leak'ni fosh qildi (reels
    fullscreen overlay ostida ko'rinmas edi). Ko'p qatorli izoh: {% comment %}.
    """
    from django.conf import settings

    bad = []
    for tpl in (settings.BASE_DIR / "templates").rglob("*.html"):
        for n, line in enumerate(tpl.read_text(encoding="utf-8").splitlines(), 1):
            if "{#" in line and "#}" not in line:
                bad.append(f"{tpl.relative_to(settings.BASE_DIR)}:{n}")
    assert not bad, f"Ko'p qatorli {{# ... #}} izoh (matn-leak): {bad}"
