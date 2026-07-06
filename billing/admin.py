"""billing/admin.py — buyurtmalar audit ko'rinishi [P7-T2].

Faqat o'qish: to'lov holati provider (Payme) va ledger tomonidan boshqariladi;
admin qo'lda o'zgartirishi double-credit/nomuvofiqlik xavfi tug'diradi.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin

from billing.models import Order


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["id", "user", "provider", "amount_uzs", "coins", "status", "created_at"]
    list_filter = ["provider", "status", "created_at"]
    search_fields = ["id", "provider_txn_id", "user__username", "user__email"]
    list_select_related = ["user"]
    readonly_fields = [
        "id",
        "user",
        "provider",
        "amount_uzs",
        "coins",
        "status",
        "provider_txn_id",
        "provider_state",
        "cancel_reason",
        "created_at",
        "provider_created_at",
        "paid_at",
        "canceled_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
