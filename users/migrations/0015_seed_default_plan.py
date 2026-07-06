# users/migrations/0015 — default reja + legacy premium backfill [P7-T1]
#
# 1) "VIP 1 oy" rejasi (15 Coin / 30 kun) — eski buy_premium hardcode narxi
#    bilan bir xil, mavjud oqim uzilmaydi.
# 2) is_premium=True profillarga Subscription qatori ochiladi (end=premium_until,
#    None bo'lsa muddatsiz) — premium holat reja-asosli tizimga ko'chadi.
# Reverse: noop — 0014 reverse jadvalning o'zini o'chiradi.

from django.db import migrations
from django.utils import timezone

DEFAULT_PERKS = "Mutlaqo reklamasiz\nYopiq VIP qismlar\nMaxsus Premium status"


def seed_and_backfill(apps, schema_editor):
    SubscriptionPlan = apps.get_model("users", "SubscriptionPlan")
    Subscription = apps.get_model("users", "Subscription")
    Profile = apps.get_model("users", "Profile")

    plan, _created = SubscriptionPlan.objects.get_or_create(
        name="VIP 1 oy",
        defaults={
            "price_coins": 15,
            "duration_days": 30,
            "perks": DEFAULT_PERKS,
            "is_active": True,
            "sort_order": 0,
        },
    )

    now = timezone.now()
    premium_profiles = Profile.objects.filter(is_premium=True).exclude(
        subscriptions__status="active"
    )
    Subscription.objects.bulk_create(
        Subscription(
            profile=profile,
            plan=plan,
            status="active",
            start_at=now,
            end_at=profile.premium_until,  # None -> muddatsiz (hujjatlangan)
            auto_renew=False,
        )
        for profile in premium_profiles
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0014_subscriptionplan_subscription"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, migrations.RunPython.noop),
    ]
