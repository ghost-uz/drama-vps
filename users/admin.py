from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, StackedInline

# MANA SHU QATORNI QO'SHING:
from unfold.decorators import display

from .models import (
    CoinTransaction,
    CryptoTopUpRequest,
    Notification,
    Profile,
    Subscription,
    SubscriptionPlan,
    TopUpRequest,
)


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


@admin.register(CoinTransaction)
class CoinTransactionAdmin(ModelAdmin):
    """Coin ledger — faqat o'qish uchun audit ko'rinishi (o'zgarmas yozuvlar)."""

    list_display = ["created_at", "profile", "type", "amount", "balance_after", "reference"]
    list_filter = ["type", "created_at"]
    search_fields = ["profile__user__username", "reference", "description"]
    list_select_related = ["profile__user"]
    readonly_fields = [
        "profile",
        "amount",
        "type",
        "balance_after",
        "description",
        "reference",
        "created_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ModelAdmin):
    """Obuna rejalari — narx/muddat/imtiyozlar admin'da boshqariladi [P7-T1]."""

    list_display = ["name", "price_coins", "duration_days", "is_active", "sort_order"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    ordering = ["sort_order", "price_coins"]


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    """Obunalar — holat/muddat nazorati; bekor qilish keshni ham sinxronlaydi [P7-T1]."""

    list_display = ["profile", "plan", "get_status", "start_at", "end_at", "auto_renew"]
    list_filter = ["status", "auto_renew", "plan"]
    search_fields = ["profile__user__username", "profile__user__email"]
    list_select_related = ["profile__user", "plan"]
    readonly_fields = ["created_at", "updated_at"]
    actions = ["cancel_subscriptions"]

    @admin.display(description="Holati")
    def get_status(self, obj):
        colors = {
            "active": "bg-green-500 text-white",
            "expired": "bg-gray-500 text-white",
            "canceled": "bg-red-500 text-white",
        }
        css = colors.get(obj.status, "bg-yellow-500 text-black")
        return mark_safe(  # noqa: S308 — statik matn, foydalanuvchi kiritmasi emas
            f'<span class="{css} px-2 py-1 rounded text-xs font-bold">'
            f"{obj.get_status_display()}</span>"
        )

    @admin.action(description="BEKOR QILISH (coin qaytarilmaydi, kesh sinxronlanadi)")
    def cancel_subscriptions(self, request, queryset):
        from users.services import subscriptions

        count = 0
        for sub in queryset.filter(status=Subscription.Status.ACTIVE).select_related("profile"):
            subscriptions.cancel(sub)
            count += 1
        self.message_user(request, f"{count} ta obuna bekor qilindi.")


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    """Sayt ichidagi bildirishnomalar [P6-T3]. Admin qo'lda 'system' e'lon yubora oladi."""

    list_display = ["recipient", "kind", "title", "is_read", "created_at"]
    list_filter = ["kind", "is_read", "created_at"]
    search_fields = ["recipient__username", "title", "body"]
    list_select_related = ["recipient"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]
