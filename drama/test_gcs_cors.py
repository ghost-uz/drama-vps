"""`check_gcs_cors` qo'riqchisi [domen ko'chishi].

Bu yerdagi testlar TARMOQQA CHIQMAYDI: jonli bucket/CDN tekshiruvi buyruqning
o'zida (`manage.py check_gcs_cors`), bu yerda esa uning SIYOSATI va repodagi
allowlist fayli tekshiriladi.

Nega kerak: 2026-07-31 da `config/cors.json` da `["*"]` turgan, jonli
bucket'da esa faqat ESKI domen bor edi — ya'ni fayl hech qachon qo'llanmagan.
Nosozlik jim keldi (CSS/JS CORS talab qilmaydi, shrift va fetch talab qiladi):
Unfold admin ikonkalari o'z ligatura matniga aylanib qoldi. O'shanda buni
ushlaydigan test yo'q edi — mana shu bo'shliq.
"""

import json

import pytest
from django.conf import settings

from drama.management.commands.check_gcs_cors import Command


@pytest.fixture
def cors():
    return json.loads((settings.BASE_DIR / "config" / "cors.json").read_text(encoding="utf-8"))


def test_cors_json_lists_site_domain_first(cors):
    """Asosiy sayt domeni BIRINCHI origin bo'lishi shart.

    Ikki sabab: (1) u allowlist'da umuman bo'lishi kerak — bo'lmasa shriftlar
    va fetch shu domenda sinadi; (2) buyruqning chuqur (har-shrift) edge
    tekshiruvi AYNAN birinchi origin'ga qarshi bajariladi, ya'ni eng kuchli
    tekshiruv foydalanuvchilar yuradigan domenga qaratilgan bo'lishi kerak.
    """
    origins = Command._origins_ordered(cors)
    assert origins, "config/cors.json da origin yo'q"
    assert origins[0] == settings.SITE_URL, (
        f"cors.json birinchi origin'i {origins[0]!r}, lekin sayt {settings.SITE_URL!r}. "
        "Domen ko'chgan bo'lsa allowlist'ni yangilang (docs/ops/domain-migration.md §2.1)."
    )


def test_cors_json_has_no_wildcard_origin(cors):
    """`*` — 2026-07-31 dagi aynan o'sha holat: har qanday sayt assetlarni
    JS orqali o'qiy oladi va allowlist amalda o'chgan bo'ladi."""
    assert "*" not in Command._origins(cors)


def test_origins_keep_file_order():
    """Tartib SARALANMAYDI: saralansa alifbo bo'yicha eski domen birinchi
    bo'lib qolardi va chuqur tekshiruv xato nishonga qaralardi."""
    rules = [{"origin": ["https://z.example", "https://a.example", "https://z.example"]}]
    assert Command._origins_ordered(rules) == ["https://z.example", "https://a.example"]


def test_missing_origin_in_bucket_is_a_problem():
    """Repoda e'lon qilingan, bucket'da yo'q -> foydalanuvchiga KO'RINADIGAN
    nosozlik, ya'ni MUAMMO (ogohlantirish emas)."""
    repo = [{"origin": ["https://dramauz.com", "https://www.dramauz.com"]}]
    live = [{"origin": ["https://dramauz.com"]}]
    problems, warnings = Command()._classify_drift(repo, live)
    assert len(problems) == 1
    assert "https://www.dramauz.com" in problems[0]
    assert not warnings


def test_extra_origin_in_bucket_is_only_a_warning():
    """Bucket'da ortiqcha origin — shoshilinch qo'lda tuzatish bo'lishi mumkin;
    sayt ISHLAYAPTI, shu bois CI'ni sindirmaydi (siyosat qarori).

    Misol domeni ATAYLAB neytral: test siyosatni tekshiradi, aniq domenni
    emas — va `core/test_domain_migration.py` qo'riqchisi Python kodida
    eski domenga absolyut havolani taqiqlaydi.
    """
    repo = [{"origin": ["https://dramauz.com"]}]
    live = [{"origin": ["https://dramauz.com", "https://legacy.example"]}]
    problems, warnings = Command()._classify_drift(repo, live)
    assert not problems
    assert len(warnings) == 1
    assert "https://legacy.example" in warnings[0]


def test_same_origins_different_fields_is_a_warning():
    repo = [{"origin": ["https://dramauz.com"], "method": ["GET", "HEAD"]}]
    live = [{"origin": ["https://dramauz.com"], "method": ["GET"]}]
    problems, warnings = Command()._classify_drift(repo, live)
    assert not problems
    assert len(warnings) == 1


def test_wildcard_is_not_probeable():
    """`*` siyosatdagi joker — brauzer hech qachon `Origin: *` yubormaydi,
    shuning uchun u edge probe'iga kirmasligi kerak."""
    assert Command._is_probeable("https://dramauz.com")
    assert not Command._is_probeable("*")
