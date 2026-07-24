"""Til-variant URL yordamchilari (hreflang + til almashtirgich) [V2G-T1].

NEGA CONTEXT-PROCESSOR EMAS, TEG:
context-processor HAR BIR render'da ishlaydi — jumladan HTMX partial'larida
(comment_list, _movie_items va h.k.), ular esa hreflang'ga umuman muhtoj emas.
`translate_url()` ichida `resolve()` + `reverse()` bor, ya'ni tekin emas.
Teg sifatida u FAQAT base.html'ning <head> qismida, sahifada bir marta chaqiriladi.
"""

from __future__ import annotations

from typing import Any

from django import template
from django.http import HttpRequest
from django.urls import translate_url
from django.utils.translation import get_language

register = template.Library()


@register.simple_tag(takes_context=True)
def alternate_url(context: dict[str, Any], lang_code: str, absolute: bool = True) -> str:
    """Joriy sahifaning `lang_code` tilidagi URL'ini qaytaradi.

    hreflang uchun `request.path` ishlatiladi (canonical bilan bir xil shakl —
    query string'siz), aks holda `?page=2` kabi parametrlar hreflang juftligini
    cheksiz variantga bo'lib yuborardi.

    Yo'l hal bo'lmasa (masalan 404 sahifa) `translate_url` kiruvchi qiymatni
    o'zgarishsiz qaytaradi — bu xavfsiz zaxira.
    """
    request: HttpRequest | None = context.get("request")
    if request is None:
        return ""
    path = translate_url(request.path, lang_code)
    return request.build_absolute_uri(path) if absolute else path


@register.simple_tag(takes_context=True)
def switch_language_url(context: dict[str, Any], lang_code: str) -> str:
    """Til almashtirgich uchun — joriy sahifa, boshqa tilda, query saqlangan holda."""
    request: HttpRequest | None = context.get("request")
    if request is None:
        return "/"
    return translate_url(request.get_full_path(), lang_code)


@register.simple_tag
def current_language() -> str:
    """Faol til kodi (i18n context-processor'siz)."""
    return get_language() or ""
