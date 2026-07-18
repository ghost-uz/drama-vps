from django.conf import settings
from django.contrib.staticfiles.storage import ManifestFilesMixin
from storages.backends.gcloud import GoogleCloudStorage


class CustomMediaStorage(GoogleCloudStorage):
    location = "media"

    def _clean_name(self, name):
        return name.replace("\\", "/")

    def url(self, name):
        # Google API-dan so'rab o'tirmasdan, o'zimiz link yasaymiz
        name = self._clean_name(name)
        return f"https://{settings.GS_CUSTOM_DOMAIN}/{self.location}/{name}"


class CustomStaticStorage(ManifestFilesMixin, GoogleCloudStorage):
    """Hash'langan statik nomlar (cache-busting) + GCS [stale-static fix].

    Manifest'siz collectstatic GCS obyektini mtime bo'yicha "o'zgarmagan" deb
    SKIP qilardi (konteynerda mtime ishonchsiz) -> cdn.drama.uz 24h kesh bilan
    ESKI js/css tarqatardi (prod'da reels reply shu sabab ishlamagan, 2026-07-18).
    Hash'langan nom har o'zgarishda YANGI obyekt -> kesh o'z-o'zidan chetlanadi.
    staticfiles.json manifest ham GCS'da — runtime shu orqali nomni topadi.
    """

    location = "static"

    def _clean_name(self, name):
        return name.replace("\\", "/")

    def url(self, name, force=False):
        # Manifest'dan hash'langan nomni olamiz, URL'ni o'zimiz yasaymiz
        # (GoogleCloudStorage.url() Google API'ga murojaat qilardi)
        name = self._clean_name(name)
        try:
            name = self.stored_name(name)
        except ValueError:
            pass  # manifest'da yo'q (masalan, collectstatic'dan oldin)
        return f"https://{settings.GS_CUSTOM_DOMAIN}/{self.location}/{name}"
