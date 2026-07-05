from django.apps import AppConfig


class DramaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "drama"
    verbose_name = "Kino va Doramalar"  # Admin panelda app nomi qanday chiqishi

    def ready(self):
        # Kesh-invalidatsiya signallarini ulaydi [P9-T1] — importsiz signal ULANMAYDI
        from . import signals  # noqa: F401
