from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "blog"
    verbose_name = "Blog / Yangiliklar"

    def ready(self) -> None:
        # Signal'lar import qilinadi (kesh invalidatsiya)
        from . import signals  # noqa: F401
