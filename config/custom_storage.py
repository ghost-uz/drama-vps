from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage


class CustomMediaStorage(GoogleCloudStorage):
    location = "media"

    def _clean_name(self, name):
        return name.replace("\\", "/")

    def url(self, name):
        # Google API-dan so'rab o'tirmasdan, o'zimiz link yasaymiz
        name = self._clean_name(name)
        return f"https://{settings.GS_CUSTOM_DOMAIN}/{self.location}/{name}"


class CustomStaticStorage(GoogleCloudStorage):
    location = "static"

    def _clean_name(self, name):
        return name.replace("\\", "/")

    def url(self, name):
        name = self._clean_name(name)
        return f"https://{settings.GS_CUSTOM_DOMAIN}/{self.location}/{name}"
