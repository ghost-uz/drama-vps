from django.contrib import admin

from .models import FundingContributor, FundingProject


@admin.register(FundingProject)
class FundingProjectAdmin(admin.ModelAdmin):
    list_display = ("movie", "status", "collected_amount", "target_amount", "progress_percentage")
    list_editable = ("status",)
    search_fields = ("movie__title",)


@admin.register(FundingContributor)
class FundingContributorAdmin(admin.ModelAdmin):
    list_display = ("profile", "project", "amount_paid", "funded_at")
    search_fields = ("profile__user__username", "project__movie__title")
