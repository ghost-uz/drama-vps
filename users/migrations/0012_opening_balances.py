"""Mavjud (nolga teng bo'lmagan) balanslar uchun 'opening' ledger yozuvi.

Ledger invariantini (balance == SUM(amount)) tarixiy ma'lumotda ham
o'rnatadi: har profilning joriy balansi bitta boshlang'ich tranzaksiyaga
aylantiriladi.
"""

from django.db import migrations


def create_opening_balances(apps, schema_editor):
    Profile = apps.get_model("users", "Profile")
    CoinTransaction = apps.get_model("users", "CoinTransaction")

    rows = [
        CoinTransaction(
            profile_id=pk,
            amount=balance,
            type="opening",
            balance_after=balance,
            description="Ledger joriy etilishidagi boshlang'ich balans",
            reference=f"profile:{pk}",
        )
        for pk, balance in Profile.objects.exclude(balance=0).values_list("id", "balance")
    ]
    CoinTransaction.objects.bulk_create(rows, batch_size=500)


def remove_opening_balances(apps, schema_editor):
    CoinTransaction = apps.get_model("users", "CoinTransaction")
    CoinTransaction.objects.filter(type="opening").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_coin_transaction_ledger"),
    ]

    operations = [
        migrations.RunPython(create_opening_balances, remove_opening_balances),
    ]
