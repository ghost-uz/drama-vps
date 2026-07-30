"""Domen ko'chishi qo'riqchilari: drama.uz -> dramauz.com [2026-07-30].

Bu testlar "sayt ishlayaptimi" ni emas, QIDIRUV TIZIMI SIGNALLARINI tekshiradi.
Domen ko'chirilganda eng katta xavf — yangi saytning o'zi qidiruv tizimiga
"mening kanonik nusxam eski domenda" deb aytib qo'yishi: o'shanda Google ikki
domenni mustaqil (klonlangan) sayt deb baholaydi va reyting bo'linadi.

Shu sabab har bir mashina-o'qiydigan URL manbasi alohida qotirilgan:
  * sitemap    -> Site (DB) qatoridan
  * robots.txt -> so'rov xostidan
  * canonical / hreflang / og:url / JSON-LD -> so'rov xostidan
"""

from pathlib import Path

import pytest
from django.conf import settings

NEW_DOMAIN = "dramauz.com"
OLD_DOMAIN = "drama.uz"
# CDN ATAYLAB eski domenda qoldi (GCS bucket nomi domenga teng bo'lishi shart).
# Qidiruv tizimlari duplikat-kontentni SAHIFA domeni bo'yicha baholaydi, asset
# xosti bo'yicha emas — shu bois bu istisno xavfsiz.
CDN_HOST = "cdn.drama.uz"


# --- 1. Sitemap: Site (DB) qatoriga bog'liq, so'rov xostiga EMAS ---


@pytest.mark.django_db
def test_current_site_domain_is_new_domain():
    """`core/migrations/0002_site_domain_dramauz` qo'llanganini kafolatlaydi.

    Bu qator sitemap `<loc>` larining yagona manbai. `example.com` yoki
    `drama.uz` bo'lib qolsa — sitemap butunlay boshqa saytni ko'rsatadi.
    """
    from django.contrib.sites.models import Site

    assert Site.objects.get_current().domain == NEW_DOMAIN


@pytest.mark.django_db
def test_sitemap_locations_use_new_domain(client):
    xml = client.get("/sitemap.xml").content.decode()
    assert f"//{NEW_DOMAIN}/" in xml
    assert OLD_DOMAIN not in xml


@pytest.mark.django_db
def test_video_sitemap_locations_use_new_domain(client):
    """Video sitemap alohida shablon (`<video:player_loc>`) — o'z tekshiruvi bor."""
    from drama.factories import EpisodeFactory, MovieFactory

    EpisodeFactory(movie=MovieFactory(title="Domen testi"), episode_number=1)
    xml = client.get("/sitemap-video.xml").content.decode()
    assert f"//{NEW_DOMAIN}/" in xml
    assert OLD_DOMAIN not in xml


# --- 2. robots.txt: so'rov xostidan quriladi ---


@pytest.mark.django_db
def test_robots_host_and_sitemaps_follow_request_host(client):
    """`Host:` va `Sitemap:` qattiq kodlangan bo'lsa test yiqiladi.

    Test mijozi `testserver` xostidan so'raydi — javobda aynan shu ko'rinsa,
    demak qiymat so'rovdan olinmoqda (domen kelajakda yana o'zgarsa ham to'g'ri).
    """
    body = client.get("/robots.txt").content.decode()
    assert "Host: testserver" in body
    assert "Sitemap: http://testserver/sitemap.xml" in body
    assert OLD_DOMAIN not in body


# --- 3. HTML meta: canonical / og:url / JSON-LD ---


@pytest.mark.django_db
def test_home_html_metadata_follows_request_host(client):
    """canonical, og:url va WebSite JSON-LD bitta xostni ko'rsatishi shart."""
    html = client.get("/").content.decode()

    assert '<link rel="canonical" href="http://testserver/">' in html
    assert '<meta property="og:url" content="http://testserver/">' in html
    # JSON-LD WebSite: sayt "o'zim kimman" deb aytadigan joy
    assert '"url": "http://testserver/"' in html
    assert '"target": "http://testserver/search/?q={search_term_string}"' in html

    # Sahifadan eski domen umuman chiqmasin (CDN asseti bundan mustasno)
    assert OLD_DOMAIN not in html.replace(CDN_HOST, "")


@pytest.mark.django_db
def test_hreflang_alternates_follow_request_host(client):
    html = client.get("/").content.decode()
    assert '<link rel="alternate" hreflang="uz" href="http://testserver/">' in html
    assert '<link rel="alternate" hreflang="en" href="http://testserver/en/">' in html


# --- 4. Manba-kod qo'riqchilari (kelajakdagi regressiya uchun) ---


def test_no_hardcoded_old_domain_in_templates():
    """Shablonlarda eski domen QOLMASIN (CDN xostidan boshqa).

    Shablon — Google ko'radigan yagona sirt; bitta unutilgan absolyut havola
    ham "kanonik boshqa saytda" signalini qaytarib keltiradi.
    """
    leaks = []
    for html in (Path(settings.BASE_DIR) / "templates").rglob("*"):
        if not html.is_file() or html.suffix not in {".html", ".xml", ".webmanifest", ".js"}:
            continue
        text = html.read_text(encoding="utf-8", errors="ignore").replace(CDN_HOST, "")
        if OLD_DOMAIN in text:
            leaks.append(str(html.relative_to(settings.BASE_DIR)))
    assert not leaks, f"Eski domen qolgan shablonlar: {leaks}"


def test_no_absolute_old_domain_urls_in_python():
    """Python kodida eski domenga ABSOLYUT havola (`https://...`) qolmasin.

    Qidirilayotgan matn ish vaqtida quriladi — aks holda bu faylning o'zi
    "sizib chiqqan" deb topilardi (test o'zini ushlab qolardi).

    `migrations/` ATAYLAB tashlab ketiladi: migratsiya — tarixiy yozuv,
    unda eski domen nomi izoh sifatida qolishi to'g'ri.
    """
    root = Path(settings.BASE_DIR)
    skip_dirs = {"env", ".git", "node_modules", "staticfiles", ".claude", "migrations"}
    leaks = []
    for py in root.rglob("*.py"):
        if skip_dirs & set(py.relative_to(root).parts):
            continue
        if f"https://{OLD_DOMAIN}" in py.read_text(encoding="utf-8", errors="ignore"):
            leaks.append(str(py.relative_to(root)))
    assert not leaks, f"Eski domenga absolyut havola: {leaks}"
