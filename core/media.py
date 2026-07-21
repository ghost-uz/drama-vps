"""Test/e2e muhitida media fayllarni storage backend orqali serve qilish.

Prod'da media GCS/CDN'dan keladi; lokal DEBUG'da `static()` uni MEDIA_ROOT'dan
(disk) beradi. Ammo test/e2e sozlamalari `InMemoryStorage` ishlatadi — fayl
DISKDA YO'Q, shu bois `static()` / `django.views.static.serve` 404 qaytaradi:
e2e `live_server` har `<video poster>` / `<img>` so'roviga
`WARNING Not Found: /media/...` shovqinini yozadi. Bu view faylni to'g'ridan-
to'g'ri `default_storage` (xotira)dan o'qiydi. Faqat `SERVE_MEDIA_FROM_STORAGE=
True` (test settings) bilan urlconf'ga ulanadi — prod/dev'ga ta'sir qilmaydi.
"""

from __future__ import annotations

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpRequest


def serve_from_storage(request: HttpRequest, path: str) -> FileResponse:
    """`default_storage`'dagi `path` faylini oqim bilan qaytaradi (yo'q bo'lsa 404).

    Content-Type `FileResponse` tomonidan fayl nomidan aniqlanadi (masalan .jpg
    -> image/jpeg, .webp -> image/webp).
    """
    if not default_storage.exists(path):
        raise Http404(path)
    return FileResponse(default_storage.open(path, "rb"))
