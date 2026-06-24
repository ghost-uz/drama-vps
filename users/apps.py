from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self):
        # Signal receiverlarini ulaydi: profil avto-yaratish + avatar tozalash.
        # (@receiver faqat modul import qilinganda ulanadi.)
        from . import signals  # noqa: F401
