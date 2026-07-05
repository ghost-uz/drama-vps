"""P2-T1: REST API fundament smoke testlari (schema, docs, JWT)."""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_schema_endpoint(api):
    assert api.get("/api/v1/schema/").status_code == 200


@pytest.mark.django_db
def test_swagger_docs(api):
    # Swagger UI to'liq HTML -> context_processor (trending_tags) DB/keshdan o'qiydi
    assert api.get("/api/v1/docs/").status_code == 200


@pytest.mark.django_db
def test_redoc(api):
    assert api.get("/api/v1/redoc/").status_code == 200


@pytest.mark.django_db
def test_jwt_obtain_and_refresh(api):
    User.objects.create_user(username="apiuser", password="pass12345")
    resp = api.post("/api/v1/auth/token/", {"username": "apiuser", "password": "pass12345"})
    assert resp.status_code == 200
    assert "access" in resp.data and "refresh" in resp.data
    r2 = api.post("/api/v1/auth/token/refresh/", {"refresh": resp.data["refresh"]})
    assert r2.status_code == 200
    assert "access" in r2.data


@pytest.mark.django_db
def test_jwt_wrong_password(api):
    User.objects.create_user(username="apiuser2", password="pass12345")
    resp = api.post("/api/v1/auth/token/", {"username": "apiuser2", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_jwt_rotation_blacklists_old_refresh(api):
    """ROTATE + BLACKLIST: refresh ishlatilgach, eski refresh qayta ishlatilmaydi."""
    User.objects.create_user(username="apiuser3", password="pass12345")
    resp = api.post("/api/v1/auth/token/", {"username": "apiuser3", "password": "pass12345"})
    old_refresh = resp.data["refresh"]
    r1 = api.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh})
    assert r1.status_code == 200
    # Eski refresh'ni qayta ishlatish — blacklist tufayli rad etiladi
    r2 = api.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh})
    assert r2.status_code == 401


# --- P11-T3: JWT end-to-end (Bearer header bilan HAQIQIY autentifikatsiya) ---


@pytest.mark.django_db
def test_jwt_bearer_authenticates_protected_endpoint(api):
    """Olingan access token himoyalangan endpointni HAQIQATAN ochadi.

    Boshqa barcha auth testlar force_authenticate ishlatadi — bu test
    Authorization: Bearer yo'lining o'zini qamraydi (acceptance: JWT auth).
    """
    User.objects.create_user(username="jwtuser", password="pass12345")
    token = api.post("/api/v1/auth/token/", {"username": "jwtuser", "password": "pass12345"}).data
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    resp = api.get("/api/v1/me/")
    assert resp.status_code == 200
    assert "balance" in resp.data


@pytest.mark.django_db
def test_jwt_garbage_token_is_401(api):
    api.credentials(HTTP_AUTHORIZATION="Bearer bu-token-emas")
    assert api.get("/api/v1/me/").status_code == 401
