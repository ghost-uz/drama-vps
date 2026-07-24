"""Blog kontenti bilingual [V2G-T2] — movies bilan bir xil naqsh (uz fallback).

`slug` ATAYLAB yo'q: URL til-neytral (V2G-T1 hreflang juftligi buzilmasin).
"""

from modeltranslation.translator import TranslationOptions, register

from .models import Post


@register(Post)
class PostTranslationOptions(TranslationOptions):
    fields = ("title", "excerpt", "body")
