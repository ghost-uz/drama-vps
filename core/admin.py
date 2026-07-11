"""core/admin.py — AuditLog: faqat o'qiladigan jurnal [P10-T4]."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from core.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ("created_at", "actor", "action", "target", "details", "ip")
    list_filter = ("action",)
    search_fields = ("actor__username", "action", "target", "details")
    date_hierarchy = "created_at"
    list_select_related = ("actor",)

    # Jurnal O'ZGARMAS: qo'shish/tahrir/o'chirish yopiq — faqat ko'rish.
    # Aks holda audit o'z maqsadini yo'qotadi (izni o'chirish mumkin bo'lardi).
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
