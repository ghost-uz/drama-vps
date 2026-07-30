"""Site.domain: drama.uz -> dramauz.com [DOMEN-KO'CHISH 2026-07-30].

NEGA MIGRATSIYA, admin'dan qo'lda tahrir EMAS
---------------------------------------------
Django sitemap freymvorki `<loc>` uchun domenni so'rov xostidan emas,
`django.contrib.sites` DB qatoridan oladi (`get_current_site()` — SITE_ID=1).
Ya'ni bu qator eski domenda qolsa, YANGI domendagi /sitemap.xml va
/sitemap-video.xml Google'ga `https://drama.uz/...` ro'yxatini beradi:
"kanonik kontent boshqa saytda" degan eng kuchli duplikat-signali —
aynan sayt "klonlangan" deb baholanadigan holat.

Qo'lda tahrir faqat bitta bazani tuzatardi; migratsiya esa prod, staging va
har bir yangi dev/test bazasini bir xil holatga keltiradi (aks holda yangi
baza Django default'i `example.com` bilan qolib ketadi). allauth ham
email shablonlarida shu qatordan foydalanadi.

Domen ATAYLAB qattiq yozilgan (settings'dan o'qilmaydi): migratsiya —
tarixiy yozuv, uning natijasi qaysi muhitda ishga tushirilishiga qarab
o'zgarib ketmasligi kerak.
"""

from django.db import migrations

NEW_DOMAIN = "dramauz.com"
OLD_DOMAIN = "drama.uz"
SITE_PK = 1  # settings.SITE_ID — tarixiy qiymat, shu bois qattiq yozilgan


def set_new_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        pk=SITE_PK,
        defaults={"domain": NEW_DOMAIN, "name": NEW_DOMAIN},
    )


def restore_old_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=SITE_PK).update(domain=OLD_DOMAIN, name=OLD_DOMAIN)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_audit_log"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(set_new_domain, restore_old_domain)]
