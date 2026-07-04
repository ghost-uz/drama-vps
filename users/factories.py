"""factory_boy fabrikalari — users app [P11-T1].

ProfileFactory ATAYIN yo'q: Profile post_save signalida (users/signals.py,
get_or_create) avtomatik yaratiladi — alohida fabrika signal bilan dublikat/
to'qnashuv manbai bo'lardi. Profil maydonlarini o'zgartirish:

    user = UserFactory()
    user.profile.is_premium = True
    user.profile.save()
"""

import factory
from django.contrib.auth.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@test.uz")
    password = factory.django.Password("pass12345")
