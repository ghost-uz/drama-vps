"""/.well-known/agent-index.json (DNS-AID _index backing doc) testlari."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_agent_index_serves_json_catalog(client):
    """Indeks JSON qaytaradi va MAVJUD API resurslarini absolyut URL bilan
    ro'yxatlaydi (service-desc + service-doc) — DNS-AID _index entrypoint.
    """
    resp = client.get("/.well-known/agent-index.json")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")

    data = resp.json()
    assert data["name"] == "Drama.uz"
    assert data["homepage"].startswith("http")

    rels = {s["rel"]: s for s in data["services"]}
    assert "service-desc" in rels
    assert "service-doc" in rels
    # Havolalar absolyut va haqiqiy endpointlarga ishora qiladi
    assert rels["service-desc"]["href"].startswith("http")
    assert reverse("api:schema") in rels["service-desc"]["href"]
    assert reverse("api:docs") in rels["service-doc"]["href"]
    # ...va jonli (404 emas) — "faqat mavjudini e'lon qil" invarianti
    assert client.get(reverse("api:schema")).status_code == 200
    assert client.get(reverse("api:docs")).status_code == 200


def test_agent_index_url_name_resolves():
    """URL nomi kutilgan well-known yo'lga hal bo'ladi (routing regressiya guardi)."""
    assert reverse("agent_index") == "/.well-known/agent-index.json"
