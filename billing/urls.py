"""billing/urls.py — checkout + Payme webhook [P7-T2]."""

from django.urls import path

from billing import views, webhooks

app_name = "billing"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    # Payme merchant endpoint (Payme panelida SHU URL ko'rsatiladi)
    path("payme/webhook/", webhooks.payme_webhook, name="payme_webhook"),
]
