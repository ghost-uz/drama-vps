"""Admin 2FA + audit-log testlari [P10-T4]."""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.models import AuditLog
from drama.factories import MovieFactory
from drama.models import Movie
from users.models import TopUpRequest


def _staff(username="boss"):
    return User.objects.create_superuser(username, f"{username}@test.uz", "pass12345")


def _token(device):
    """Qurilmaning JORIY haqiqiy TOTP tokeni (testda authenticator o'rnida)."""
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    return f"{totp.token():06d}"


# --- bootstrap_totp buyrug'i ---


@pytest.mark.django_db
def test_bootstrap_totp_creates_confirmed_device(capsys):
    user = _staff()
    call_command("bootstrap_totp", user.username)
    device = TOTPDevice.objects.get(user=user)
    assert device.confirmed is True
    assert "otpauth://" in capsys.readouterr().out
    # idempotent — takror chaqiruv ikkinchi qurilma ochmaydi
    call_command("bootstrap_totp", user.username)
    assert TOTPDevice.objects.filter(user=user).count() == 1


# --- 2FA enforcement (middleware + verify sahifa) ---


@pytest.mark.django_db
def test_admin_2fa_redirects_unverified_staff(client, settings):
    settings.ADMIN_REQUIRE_2FA = True
    client.force_login(_staff())
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/admin-2fa/")
    # qurilmasiz — sahifa bootstrap ko'rsatmasini beradi
    resp = client.get("/admin-2fa/")
    assert resp.status_code == 200
    assert "bootstrap_totp" in resp.content.decode()


@pytest.mark.django_db
def test_admin_2fa_full_flow_with_token(client, settings):
    settings.ADMIN_REQUIRE_2FA = True
    user = _staff("boss2")
    device = TOTPDevice.objects.create(user=user, name="asosiy", confirmed=True)
    client.force_login(user)
    assert client.get("/admin/").status_code == 302  # hali tasdiqlanmagan

    resp = client.post(
        "/admin-2fa/",
        {"otp_device": device.persistent_id, "otp_token": _token(device)},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/"
    assert client.get("/admin/").status_code == 200  # endi ochiq


@pytest.mark.django_db
def test_admin_2fa_wrong_token_rejected(client, settings):
    settings.ADMIN_REQUIRE_2FA = True
    user = _staff("boss3")
    device = TOTPDevice.objects.create(user=user, name="asosiy", confirmed=True)
    client.force_login(user)
    resp = client.post("/admin-2fa/", {"otp_device": device.persistent_id, "otp_token": "abcdef"})
    assert resp.status_code == 200  # forma xato bilan qayta chiziladi
    assert client.get("/admin/").status_code == 302  # hali ham yopiq


@pytest.mark.django_db
def test_admin_2fa_flag_off_passthrough(client):
    """Dev/test default (False): qurilmasiz staff admin'ga kiradi — regressiya guardi."""
    client.force_login(_staff("boss4"))
    assert client.get("/admin/").status_code == 200


@pytest.mark.django_db
def test_admin_logout_allowed_without_2fa(client, settings):
    """Tasdiqlanmagan sessiya ham logout qila oladi (qulf yo'q)."""
    settings.ADMIN_REQUIRE_2FA = True
    client.force_login(_staff("boss5"))
    resp = client.post("/admin/logout/")
    assert resp.status_code in (200, 302)  # 2FA sahifasiga YO'NALTIRILMAYDI
    assert not resp.headers.get("Location", "").startswith("/admin-2fa/")


# --- audit jurnali ---


@pytest.mark.django_db
def test_topup_approve_writes_audit(client):
    admin_user = _staff("auditboss")
    client.force_login(admin_user)
    buyer = User.objects.create_user("buyer1", "b@test.uz", "pass12345")
    req = TopUpRequest.objects.create(
        user=buyer,
        amount_uzs=50000,
        receipt_image=SimpleUploadedFile("chek.jpg", b"fake-image-bytes", "image/jpeg"),
    )
    resp = client.post(
        reverse("admin:users_topuprequest_changelist"),
        {"action": "approve_requests", "_selected_action": [str(req.pk)]},
    )
    assert resp.status_code == 302
    entry = AuditLog.objects.get(action="topup.approve")
    assert entry.actor == admin_user
    assert entry.target == f"TopUpRequest#{req.pk}"
    assert "buyer1" in entry.details


@pytest.mark.django_db
def test_movie_publish_action_writes_audit(client):
    client.force_login(_staff("pubboss"))
    movie = MovieFactory(status=Movie.Status.DRAFT)
    resp = client.post(
        reverse("admin:drama_movie_changelist"),
        {"action": "publish_movies", "_selected_action": [str(movie.pk)]},
    )
    assert resp.status_code == 302
    movie.refresh_from_db()
    assert movie.status == Movie.Status.PUBLISHED
    entry = AuditLog.objects.get(action="movie.publish")
    assert "1 ta kino" in entry.details


@pytest.mark.django_db
def test_audit_admin_is_readonly():
    """Jurnal o'zgarmasligi admin darajasida qotirilgan."""
    from django.contrib import admin as dj_admin

    model_admin = dj_admin.site._registry[AuditLog]
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


# --- CSP: statika CDN hosti script-src'da ---


@pytest.mark.django_db
def test_csp_script_src_allows_static_cdn(client):
    """Prod'da STATIC_URL = cdn.drama.uz (GCS CDN) — script-src uni o'z ichiga
    olmasa brauzer BUTUN birinchi-tomon JS'ni bloklaydi: sayt htmx/Alpine'siz,
    admin login esa unfold x-cloak sabab butunlay oq ekran. Regressiya qo'riqchisi.
    """
    for path in ("/", "/admin/login/"):
        csp = client.get(path)["Content-Security-Policy"]
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        assert "cdn.drama.uz" in script_src, path

    # P14-T1 invarianti buzilmadi: eval FAQAT admin variantida
    assert "'unsafe-eval'" in client.get("/admin/login/")["Content-Security-Policy"]
    assert "'unsafe-eval'" not in client.get("/")["Content-Security-Policy"]


# --- Link: agent-discovery sarlavhasi [RFC 8288 / RFC 9727] ---


@pytest.mark.django_db
def test_homepage_advertises_api_discovery_links(client):
    """Bosh sahifa HTML javobi Link sarlavhasida MAVJUD API resurslarini e'lon
    qiladi (RFC 8288): avtomatlashgan agentlar HTML'ni tahlil qilmasdan OpenAPI
    sxemasi (service-desc) va Swagger hujjatini (service-doc) topa oladi.
    """
    resp = client.get("/")
    assert resp.status_code == 200

    link = resp["Link"]
    assert 'rel="service-desc"' in link
    assert 'rel="service-doc"' in link
    # Agentlar uchun media-type maslahati (mashina o'qiydigan JSON OpenAPI)
    assert "application/vnd.oai.openapi+json" in link

    # Havolalar HAQIQATAN mavjud endpointlarga ishora qiladi (404 emas) —
    # "faqat mavjudini e'lon qil" invarianti (Link reverse() bilan quriladi).
    schema_url, docs_url = reverse("api:schema"), reverse("api:docs")
    assert schema_url in link
    assert docs_url in link
    assert client.get(schema_url).status_code == 200
    assert client.get(docs_url).status_code == 200


@pytest.mark.django_db
def test_discovery_link_scoped_to_html_only(client):
    """Discovery Link FAQAT text/html javoblarga qo'shiladi — API/JSON, media va
    HLS video-segment javoblari ifloslantirilmaydi. robots.txt (text/plain)
    scoping regressiya qo'riqchisi sifatida.
    """
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert "service-desc" not in resp.get("Link", "")
