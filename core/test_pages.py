"""Huquqiy sahifalar testlari [P10-T5 qisman] — oferta/maxfiylik, footer, sitemap."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_terms_page_renders(client):
    resp = client.get("/shartlar/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Foydalanish shartlari" in body
    assert "Coin" in body  # platformaga xos qoidalar bor
    assert "avtomatik va to'liq qaytariladi" in body  # P7-T4 refund kafolati aks etgan


@pytest.mark.django_db
def test_privacy_page_renders(client):
    resp = client.get("/maxfiylik/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Maxfiylik siyosati" in body
    assert "Yandex Metrika" in body  # uchinchi tomonlar halol sanab o'tilgan
    assert "Bank kartangiz raqami bizda saqlanmaydi" in body


@pytest.mark.django_db
def test_footer_links_no_dead_anchor(client):
    """Footer'dagi eski '#' havola real sahifalarga almashgan."""
    body = client.get("/").content.decode()
    assert reverse("terms") in body
    assert reverse("privacy") in body
    assert "Qoidalar va Shartlar</a>" not in body  # eski o'lik havola yo'q


@pytest.mark.django_db
def test_register_shows_consent_links(client):
    body = client.get(reverse("users:register")).content.decode()
    assert reverse("terms") in body
    assert "rozilik bildirasiz" in body


@pytest.mark.django_db
def test_legal_pages_in_sitemap(client):
    body = client.get("/sitemap.xml").content.decode()
    assert "/shartlar/" in body
    assert "/maxfiylik/" in body
