from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, StackedInline

# MANA SHU QATORNI QO'SHING:
from unfold.decorators import display

from .models import CryptoTopUpRequest, Profile, TopUpRequest


class ProfileInline(StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profil Ma'lumotlari"
    fields = ("is_premium", "premium_until", "avatar", "bio", "telegram_id")


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    inlines = (ProfileInline,)
    list_display = ("username", "email", "get_is_premium", "is_staff")

    @display(description="VIP Status", boolean=True)
    def get_is_premium(self, instance):
        try:
            # users/models.py dagi property-ni chaqiramiz
            return instance.profile.is_currently_premium
        except (AttributeError, Profile.DoesNotExist):
            return False


# users/admin.py ichiga quyidagilarni qo'shing:


@admin.register(TopUpRequest)
class TopUpRequestAdmin(ModelAdmin):
    list_display = ["user", "amount_uzs", "points", "get_status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["points", "get_receipt_image"]

    # Holatni o'zgartirish uchun qulay Unfold Action tugmalari
    actions = ["approve_requests", "reject_requests"]

    @admin.display(description="Holati")
    def get_status(self, obj):
        if obj.status == "approved":
            return mark_safe(
                '<span class="bg-green-500 text-white px-2 py-1 rounded text-xs font-bold">Tasdiqlandi</span>'
            )
        elif obj.status == "rejected":
            return mark_safe(
                '<span class="bg-red-500 text-white px-2 py-1 rounded text-xs font-bold">Rad etildi</span>'
            )
        return mark_safe(
            '<span class="bg-yellow-500 text-black px-2 py-1 rounded text-xs font-bold">Kutilmoqda</span>'
        )

    @admin.display(description="To'lov cheki")
    def get_receipt_image(self, obj):
        if obj.receipt_image:
            return mark_safe(
                f'<a href="{obj.receipt_image.url}" target="_blank"><img src="{obj.receipt_image.url}" width="300" style="border-radius:10px;"/></a>'
            )
        return "Chek yuklanmagan"

    @admin.action(description="Tanlanganlarni TASDIQLASH")
    def approve_requests(self, request, queryset):
        for req in queryset.filter(status="pending"):
            req.status = "approved"
            req.save()  # save() chaqirilganda modeldagi point qo'shish mantiqi ishlaydi
        self.message_user(request, "Tanlangan so'rovlar tasdiqlandi va pointlar berildi.")

    @admin.action(description="Tanlanganlarni RAD ETISH")
    def reject_requests(self, request, queryset):
        queryset.filter(status="pending").update(status="rejected")
        self.message_user(request, "Tanlangan so'rovlar rad etildi.")


@admin.register(CryptoTopUpRequest)
class CryptoTopUpRequestAdmin(ModelAdmin):
    list_display = ["user", "amount_usdt", "points", "get_status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["points", "get_receipt_image"]
    actions = ["approve_requests", "reject_requests"]

    @admin.display(description="Holati")
    def get_status(self, obj):
        if obj.status == "approved":
            return mark_safe(
                '<span class="bg-green-500 text-white px-2 py-1 rounded text-xs font-bold">Tasdiqlandi</span>'
            )
        elif obj.status == "rejected":
            return mark_safe(
                '<span class="bg-red-500 text-white px-2 py-1 rounded text-xs font-bold">Rad etildi</span>'
            )
        return mark_safe(
            '<span class="bg-yellow-500 text-black px-2 py-1 rounded text-xs font-bold">Kutilmoqda</span>'
        )

    @admin.display(description="To'lov skrinshotı")
    def get_receipt_image(self, obj):
        if obj.receipt_image:
            return mark_safe(
                f'<a href="{obj.receipt_image.url}" target="_blank"><img src="{obj.receipt_image.url}" width="300" style="border-radius:10px;"/></a>'
            )
        return "Skrinshot yuklanmagan"

    @admin.action(description="Tanlanganlarni TASDIQLASH")
    def approve_requests(self, request, queryset):
        for req in queryset.filter(status="pending"):
            req.status = "approved"
            req.save()
        self.message_user(request, "Tanlangan so'rovlar tasdiqlandi va coinlar berildi.")

    @admin.action(description="Tanlanganlarni RAD ETISH")
    def reject_requests(self, request, queryset):
        queryset.filter(status="pending").update(status="rejected")
        self.message_user(request, "Tanlangan so'rovlar rad etildi.")
