"""billing/models.py — to'lov buyurtmasi (Order) [P7-T2].

Order = provider-neytral to'lov niyati (N Coin = M UZS). Foydalanuvchi
checkout boshlaganda yaratiladi; provider (Payme/Click) webhook orqali holatni
o'zgartiradi. Coin FAQAT wallet ledger orqali qo'shiladi (P1-T4 invarianti) —
`billing.services.mark_paid` yagona kredit nuqtasi (idempotent).

Payme holat mashinasi (provider_state): 1=yaratilgan, 2=to'langan,
-1=yaratilgandan keyin bekor, -2=to'langandan keyin bekor. Bu Payme Merchant
API talab qiladigan qiymatlar (o'zgartirmang).
"""

import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Provider(models.TextChoices):
        PAYME = "payme", "Payme"
        CLICK = "click", "Click"

    class Status(models.TextChoices):
        CREATED = "created", "Yaratilgan"
        PAID = "paid", "To'langan"
        CANCELED = "canceled", "Bekor qilingan"

    # UUID pk — provider hisobварag'iga (account) uzatiladi; ketma-ket ID sizib
    # boshqa buyurtmalarni taxmin qilishga yo'l qo'ymaydi.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    provider = models.CharField("Provider", max_length=10, choices=Provider.choices)
    amount_uzs = models.PositiveIntegerField("Summa (UZS)")
    coins = models.PositiveIntegerField("Beriladigan Coin")
    status = models.CharField(
        "Holat", max_length=10, choices=Status.choices, default=Status.CREATED
    )

    # --- Provider tranzaksiya kuzatuvi ---
    provider_txn_id = models.CharField("Provider tranzaksiya ID", max_length=64, blank=True)
    # Payme: 1/2/-1/-2 (yuqoridagi izoh). Click keyin o'z semantikasini qo'yadi.
    provider_state = models.IntegerField("Provider holati", null=True, blank=True)
    cancel_reason = models.IntegerField("Bekor sababi (Payme kodi)", null=True, blank=True)

    created_at = models.DateTimeField("Yaratildi", auto_now_add=True)
    # Provider tranzaksiyasi yaratilgan vaqt (Payme CreateTransaction) — order
    # yaratilishidan farq qiladi; Payme create_time shu yerdan qaytariladi.
    provider_created_at = models.DateTimeField("Provider tranzaksiya vaqti", null=True, blank=True)
    paid_at = models.DateTimeField("To'landi", null=True, blank=True)
    canceled_at = models.DateTimeField("Bekor qilindi", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "provider_txn_id"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        verbose_name = "To'lov buyurtmasi"
        verbose_name_plural = "To'lov buyurtmalari"

    def __str__(self):
        return f"{self.get_provider_display()} #{self.id} — {self.amount_uzs} UZS ({self.status})"

    @property
    def amount_tiyin(self) -> int:
        """Payme summani tiyinda kutadi (1 UZS = 100 tiyin)."""
        return self.amount_uzs * 100
