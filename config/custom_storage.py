from django.conf import settings
from django.contrib.staticfiles.storage import ManifestFilesMixin
from storages.backends.gcloud import GoogleCloudStorage


class CustomMediaStorage(GoogleCloudStorage):
    location = "media"

    # [P9-T3] Media nomlari RandomFileName — qayta ishlatilmaydi (yangi yuklash =
    # yangi nom) -> 30 kun kesh xavfsiz. "immutable" EMAS: profile_pics/default.jpg
    # kabi turg'un-nomli fayllar ham shu storage'da.
    object_parameters = {"cache_control": "public, max-age=2592000"}

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

    # [P9-T3] Nomlar Manifest-hash'langan (mazmun o'zgarsa nom o'zgaradi) ->
    # 1 yil + immutable: brauzer/CDN revalidatsiya so'rovi umuman yubormaydi.
    object_parameters = {"cache_control": "public, max-age=31536000, immutable"}

    # FAQAT CSS url()/@import qayta yoziladi. Django default'idagi JS
    # sourceMappingURL/ES-import qayta yozish O'CHIRILGAN — vendor minified
    # js'larda .map fayllar repoda yo'q, collectstatic ValueError bilan
    # yiqilardi (lokal simulyatsiyada ushlangan). CSS'dagi sourceMappingURL
    # subpattern'i ham xuddi shu sababdan kiritilmagan.
    patterns = (
        (
            "*.css",
            (
                r"""(?P<matched>url\(['"]{0,1}\s*(?P<url>.*?)["']{0,1}\))""",
                (
                    r"""(?P<matched>@import\s*["']\s*(?P<url>.*?)["'])""",
                    """@import url("%(url)s")""",
                ),
            ),
        ),
    )

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
