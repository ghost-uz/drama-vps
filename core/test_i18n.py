"""i18n / to'liq EN locale testlari [V2G-T1].

Qamrov:
  * URL yo'nalishi ikkala tilda (prefikssiz uz default + /en/ prefiks)
  * til-neytral yo'llar prefiks OLMAYDI (webhook/sitemap/sw/api/allauth)
  * hreflang uz/en/x-default + canonical <head>'da
  * UI stringlari haqiqatan tarjima bo'ladi + uz fallback ishlaydi
  * til almashtirgich va set_language sessiyaga yozadi
  * sof-Python katalog vositalari (.po parse/yozish, .mo kompilyatsiya)
  * .mo fayl .po bilan sinxron (drift guard — repo'dagi .mo eskirmagan)
"""

from __future__ import annotations

import gettext
import io
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import resolve, reverse, translate_url
from django.utils import translation

from core import i18n_catalog as cat
from drama.factories import MovieFactory


# ---------------------------------------------------------------------------
# URL yo'nalishi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,args",
    [
        ("drama:movie_list", None),
        ("drama:explore", None),
        ("terms", None),
        ("users:register", None),
    ],
)
def test_reverse_prefixes_en_only(name, args):
    """uz (default) prefikssiz; en `/en/` bilan."""
    with translation.override("uz"):
        uz_url = reverse(name, args=args)
    with translation.override("en"):
        en_url = reverse(name, args=args)
    assert not uz_url.startswith("/en/")
    assert en_url == f"/en{uz_url}"


@pytest.mark.parametrize(
    "name",
    [
        "service_worker",
        "healthz",
        "bunny_webhook",
        "manifest",
        "agent_index",
        "django.contrib.sitemaps.views.sitemap",
    ],
)
def test_language_neutral_urls_never_prefixed(name):
    """Webhook/sitemap/PWA/health — til faol bo'lsa ham prefiks OLMAYDI."""
    with translation.override("uz"):
        uz_url = reverse(name)
    with translation.override("en"):
        en_url = reverse(name)
    assert uz_url == en_url
    assert not en_url.startswith("/en/")


def test_allauth_callback_not_prefixed():
    """allauth OAuth callback /en/ ostiga tushmasligi SHART (redirect_uri_mismatch oldini oladi)."""
    with translation.override("en"):
        url = reverse("google_callback")
    assert not url.startswith("/en/"), url


@pytest.mark.parametrize("lang,prefix", [("uz", ""), ("en", "/en")])
def test_resolve_both_languages(lang, prefix):
    with translation.override(lang):
        match = resolve(f"{prefix}/explore/")
    assert match.view_name == "drama:explore"


# ---------------------------------------------------------------------------
# Middleware orqali jonli render
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_home_uz_default(client):
    MovieFactory()
    resp = client.get("/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert '<html lang="uz">' in body
    assert "Barcha dramalar" in body
    assert "All dramas" not in body


@pytest.mark.django_db
def test_home_en_translated(client):
    MovieFactory()
    resp = client.get("/en/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert '<html lang="en">' in body
    assert "All dramas" in body
    assert "Barcha dramalar" not in body
    assert resp.headers.get("Content-Language") == "en"


@pytest.mark.django_db
def test_unprefixed_url_ignores_accept_language(client):
    """prefix_default_language=False: prefikssiz yo'l DOIM default til (URL = haqiqat manbai).

    Ingliz brauzer `/` so'rasa ham o'zbekcha keladi — hreflang bilan ziddiyat yo'q.
    """
    MovieFactory()
    resp = client.get("/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
    body = resp.content.decode()
    assert '<html lang="uz">' in body
    assert "Barcha dramalar" in body


@pytest.mark.django_db
def test_hreflang_and_canonical_render(client):
    resp = client.get("/explore/")
    body = resp.content.decode()
    assert '<link rel="canonical"' in body
    assert 'hreflang="uz"' in body
    assert 'hreflang="en"' in body
    assert 'hreflang="x-default"' in body
    # en varianti /en/ yo'lini ko'rsatishi kerak
    assert "/en/explore/" in body


@pytest.mark.django_db
def test_language_switcher_present(client):
    resp = client.get("/")
    body = resp.content.decode()
    # Footer'dagi til almashtirgich ikkala til havolasini beradi
    assert "/en/" in body  # en havolasi
    assert 'aria-current="true"' in body  # joriy til belgilangan


@pytest.mark.django_db
def test_set_language_writes_session(client):
    """i18n/setlang sessiyaga tilni yozadi (til-neytral endpoint, prefikssiz)."""
    resp = client.post(
        "/i18n/setlang/",
        {"language": "en", "next": "/"},
        HTTP_HOST="testserver",
    )
    assert resp.status_code in (302, 200)
    assert settings.LANGUAGE_COOKIE_NAME in resp.cookies or "_language" in client.session


# ---------------------------------------------------------------------------
# Fallback: tarjimasiz string uz msgid'ga qaytadi
# ---------------------------------------------------------------------------
def test_untranslated_falls_back_to_uzbek():
    from django.utils.translation import gettext

    with translation.override("en"):
        assert gettext("Yordam") == "Help"  # tarjima bor
        # katalogda yo'q string — msgid o'zi qaytadi (bo'sh satr EMAS)
        assert gettext("__mavjud_bo'lmagan_satr__") == "__mavjud_bo'lmagan_satr__"


def test_translation_switch_is_per_request():
    from django.utils.translation import gettext

    with translation.override("uz"):
        assert gettext("Bekor qilish") == "Bekor qilish"
    with translation.override("en"):
        assert gettext("Bekor qilish") == "Cancel"


# ---------------------------------------------------------------------------
# translate_url yordamchisi (hreflang teg asosida)
# ---------------------------------------------------------------------------
def test_translate_url_roundtrip():
    # translate_url joriy FAOL tilda resolve qiladi — switcher tegi ham xuddi shunday
    # chaqiriladi (ko'rilayotgan sahifaning tili faol). Shuning uchun har yo'nalishni
    # mos manba-til kontekstida tekshiramiz.
    with translation.override("uz"):
        assert translate_url("/explore/", "en") == "/en/explore/"
    with translation.override("en"):
        assert translate_url("/en/explore/", "uz") == "/explore/"


# ---------------------------------------------------------------------------
# Sof-Python katalog vositalari
# ---------------------------------------------------------------------------
def test_po_roundtrip_stable():
    entries = [
        cat.Entry(msgid="Yordam", msgstr=["Help"], references=["templates/base.html:1"]),
        cat.Entry(
            msgid="salom %(name)s",
            msgstr=["hello %(name)s"],
            comments=["Translators: greeting"],
        ),
    ]
    text = cat.format_po(
        entries, 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n'
    )
    reparsed = [e for e in cat.parse_po(text) if e.msgid]
    assert {(e.msgid, tuple(e.msgstr)) for e in reparsed} == {
        (e.msgid, tuple(e.msgstr)) for e in entries
    }


def test_compile_mo_readable_by_stdlib_gettext():
    """Bizning .mo GNU formatiga mos — stdlib gettext (Django ishlatadigan) o'qiy oladi."""
    entries = [
        cat.Entry(msgid="", msgstr=["Content-Type: text/plain; charset=UTF-8\n"]),
        cat.Entry(msgid="Yordam", msgstr=["Help"]),
        cat.Entry(msgid="Bo'sh", msgstr=[""]),  # tarjimasiz — TASHLANISHI kerak
    ]
    blob = cat.compile_mo(entries)
    tr = gettext.GNUTranslations(io.BytesIO(blob))
    assert tr.gettext("Yordam") == "Help"
    # tarjimasiz yozuv .mo'ga tushmaydi -> msgid'ga fallback (bo'sh satr EMAS)
    assert tr.gettext("Bo'sh") == "Bo'sh"
    assert tr.gettext("Yo'q") == "Yo'q"


def test_extract_template_trans_and_blocktrans():
    src = (
        "{% load i18n %}\n"
        '<h1>{% trans "Yordam" %}</h1>\n'
        "{% blocktrans %}Salom {{ user }}{% endblocktrans %}\n"
    )
    entries = cat.merge_extracted(cat.extract_template(src, "t.html"))
    ids = {e.msgid for e in entries}
    assert "Yordam" in ids
    assert "Salom %(user)s" in ids


def test_extract_python_gettext_calls():
    src = 'from django.utils.translation import gettext as _\nX = _("Bekor qilindi")\n'
    entries = cat.extract_python(src, "v.py")
    assert entries[0].msgid == "Bekor qilindi"


# ---------------------------------------------------------------------------
# Drift guard — repo'dagi .mo .po bilan sinxron bo'lishi SHART
# (gettext binarlari yo'q, .mo qo'lda commit qilinadi -> eskirib qolmasin)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("locale", ["en"])
def test_committed_mo_matches_po(locale):
    root = Path(settings.LOCALE_PATHS[0]) / locale / "LC_MESSAGES"
    po_entries = cat.parse_po((root / "django.po").read_text(encoding="utf-8"))
    fresh = cat.compile_mo(po_entries)
    on_disk = (root / "django.mo").read_bytes()
    assert fresh == on_disk, "django.mo eskirgan — `manage.py pocompile` ni ishlating"


@pytest.mark.django_db
def test_sitemap_has_hreflang_alternates(client):
    """i18n sitemap har item uchun uz/en variant + hreflang alternates beradi [AC3]."""
    MovieFactory()
    resp = client.get("/sitemap.xml")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "xmlns:xhtml" in body
    assert 'hreflang="uz"' in body
    assert 'hreflang="en"' in body
    assert 'hreflang="x-default"' in body
    assert "/en/" in body  # en varianti loc/alternate'da


def test_en_catalog_fully_translated():
    """EN katalogda tarjimasiz (bo'sh msgstr) yozuv QOLMASLIGI kerak."""
    root = Path(settings.LOCALE_PATHS[0]) / "en" / "LC_MESSAGES"
    entries = [e for e in cat.parse_po((root / "django.po").read_text(encoding="utf-8")) if e.msgid]
    untranslated = [e.msgid for e in entries if not e.translated]
    assert not untranslated, f"{len(untranslated)} ta tarjimasiz: {untranslated[:5]}"
