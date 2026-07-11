from django import forms
from django.contrib import admin

from core import audit

from . import services
from .models import FundingContributor, FundingProject


class FundingProjectAdminForm(forms.ModelForm):
    """Statusni qo'lda CANCELED'ga o'tkazishni bloklaydi [P7-T4].

    Bekor qilish REFUNDSIZ bo'lib qolmasligi uchun yagona yo'l — changelist'dagi
    «Bekor qilish va hissalarni refund qilish» action (services.cancel_project).
    """

    class Meta:
        model = FundingProject
        fields = "__all__"

    def clean_status(self):
        new_status = self.cleaned_data["status"]
        old_status = (
            FundingProject.objects.filter(pk=self.instance.pk)
            .values_list("status", flat=True)
            .first()
            if self.instance.pk
            else None
        )
        if (
            new_status == FundingProject.Status.CANCELED
            and old_status != FundingProject.Status.CANCELED
        ):
            raise forms.ValidationError(
                "Bekor qilish faqat changelist'dagi «Bekor qilish va refund» action "
                "orqali — aks holda hissadorlar puli qaytarilmay qoladi."
            )
        return new_status


@admin.register(FundingProject)
class FundingProjectAdmin(admin.ModelAdmin):
    # list_editable ATAYIN yo'q [P7-T4]: changelist formset admin `form`ni
    # chetlab o'tadi — clean_status guardi ishlamay statusni refundsiz
    # CANCELED qilish mumkin bo'lardi. Status faqat obyekt sahifasida o'zgaradi.
    form = FundingProjectAdminForm
    list_display = (
        "movie",
        "status",
        "collected_amount",
        "target_amount",
        "progress_percentage",
    )
    list_filter = ("status",)
    search_fields = ("movie__title",)
    actions = ["cancel_and_refund"]

    @admin.action(description="Bekor qilish va hissalarni refund qilish")
    def cancel_and_refund(self, request, queryset):
        refunded = 0
        canceled = 0
        skipped = []
        for project in queryset:
            try:
                refunded += services.cancel_project(project.pk)
                canceled += 1
            except services.FundingError:
                skipped.append(str(project.movie))
        if canceled:
            audit.log(
                request.user,
                "funding.cancel",
                details=f"{canceled} loyiha, {refunded} hissa refund",
                request=request,
            )
        msg = f"{canceled} loyiha bekor qilindi, {refunded} hissa refund qilindi."
        if skipped:
            msg += f" O'tkazib yuborildi (released): {', '.join(skipped)}"
        self.message_user(request, msg)


@admin.register(FundingContributor)
class FundingContributorAdmin(admin.ModelAdmin):
    list_display = ("profile", "project", "amount_paid", "funded_at", "refunded_at")
    search_fields = ("profile__user__username", "project__movie__title")
