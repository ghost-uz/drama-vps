"""PWA endpointlari [P5-T6] — manifest, service worker (ildiz-scope), offline.

Nega VIEW (statik fayl emas):
  • Service worker ILDIZ scope'da (`/sw.js`) bo'lishi SHART — statik `/static/js/sw.js`
    scope'i faqat `/static/js/` bo'lardi (butun saytni qamramaydi). View + response
    `Service-Worker-Allowed: /` sarlavhasi SW ga butun saytni boshqarishga ruxsat beradi.
  • manifest view — `{% static %}` ikon URL'larini muhitga qarab to'g'ri hal qiladi
    (dev `/static/...`, prod `cdn.drama.uz/static/...`).

Nega `render_to_string(request'siz)` (`render()` emas): `render()` barcha context-
processor'larni (jumladan DB-so'rovli `trending_tags`) ishga tushiradi. Bu 3 endpoint
global kontekstga muhtoj emas va tez-tez so'raladi — request'siz render DB'ga tegmaydi.
"""

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control


@cache_control(max_age=86400)
def manifest(request: HttpRequest) -> HttpResponse:
    """Web App Manifest — o'rnatiladigan PWA metama'lumoti."""
    content = render_to_string("pwa/manifest.webmanifest")
    return HttpResponse(content, content_type="application/manifest+json")


@cache_control(max_age=0)
def service_worker(request: HttpRequest) -> HttpResponse:
    """Ildiz-scope service worker (offline shell)."""
    response = HttpResponse(render_to_string("pwa/sw.js"), content_type="application/javascript")
    # SW o'z papkasidan yuqoridagi yo'llarni boshqarishi uchun (ildiz scope)
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request: HttpRequest) -> HttpResponse:
    """SW navigatsiya-fallback sahifasi (tashqi bog'liqliksiz, o'zi-ta'minlangan)."""
    return HttpResponse(render_to_string("pwa/offline.html"), content_type="text/html")
