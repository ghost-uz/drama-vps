from django.conf import settings


class SecurityHeadersMiddleware:
    """
    Yetishmayotgan xavfsizlik sarlavhalarini qo'shadi:
    CSP (frame-ancestors bilan), Permissions-Policy, CORP, Referrer-Policy.

    [P10-T1] frame-ancestors: X_FRAME_OPTIONS='ALLOWALL' (nostandart qiymat —
    brauzerlar e'tiborsiz qoldirib istalgan saytga iframe'lashga yo'l qo'yardi)
    o'rniga aniq allowlist: o'zimiz + Telegram Web (Mini App iframe). Zamonaviy
    brauzerlar frame-ancestors bor joyda X-Frame-Options'ni e'tiborsiz
    qoldiradi; XFO=SAMEORIGIN eski brauzerlar uchun fallback (prod.py).
    Telegram mobil/desktop nativ WebView ishlatadi (iframe EMAS) — cheklov
    ularga ta'sir qilmaydi.

    TEXNIK QARZ (P5-T3 bilan yopiladi): script-src'da 'unsafe-inline' qoladi —
    shablonlarda ~30 inline event-handler (onclick=...) bor; nonce qo'shilsa
    CSP2 brauzerlar 'unsafe-inline'ni e'tiborsiz qoldirib ularni sindirardi.
    Handler'lar addEventListener'ga o'tgach nonce'ga o'tiladi. 'unsafe-eval'
    esa OLIB TASHLANDI (yagona hx-on ishlatilgan joy listener'ga almashtirildi
    — htmx hx-on new Function talab qilardi).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        bunny_cdn = getattr(settings, "BUNNY_STREAM_CDN_HOSTNAME", "*.b-cdn.net")
        if not bunny_cdn:
            bunny_cdn = "*.b-cdn.net"

        self.csp = " ".join(
            [
                # Standart manba — faqat o'zimiz
                "default-src 'self';",
                # Skriptlar: o'zimiz + CDN'lar + Yandex Metrika.
                # 'unsafe-inline' — inline handler'lar refaktor bo'lguncha (docstring).
                # unpkg.com + cdn.tailwindcss.com: base-users.html shulardan yuklaydi.
                "script-src 'self' 'unsafe-inline'"
                " cdn.jsdelivr.net"
                " cdnjs.cloudflare.com"
                " unpkg.com"
                " cdn.tailwindcss.com"
                " mc.yandex.ru"
                " mc.yandex.com;",
                # Stillar: o'zimiz + Google Fonts + FA + jsdelivr + inline stillar
                "style-src 'self' 'unsafe-inline'"
                " fonts.googleapis.com"
                " cdnjs.cloudflare.com"
                " cdn.drama.uz"
                " cdn.jsdelivr.net;",
                # Shriftlar
                "font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com cdn.drama.uz data:;",
                # Rasmlar + Yandex Metrika pikseli
                f"img-src 'self' data: blob:"
                f" cdn.drama.uz"
                f" mc.yandex.ru"
                f" mc.yandex.com"
                f" {bunny_cdn}"
                f" *.bunnycdn.com;",
                # Video/audio (HLS segmentlari Bunny CDN dan keladi)
                f"media-src 'self' blob: cdn.drama.uz {bunny_cdn} *.bunnycdn.com;",
                # Ajax/fetch/WebSocket
                f"connect-src 'self'"
                f" cdn.drama.uz"
                f" mc.yandex.ru"
                f" mc.yandex.com"
                f" {bunny_cdn}"
                f" *.bunnycdn.com;",
                # BIZ kimni iframe'laymiz (video embed)
                f"frame-src 'self'"
                f" {bunny_cdn}"
                f" *.bunnycdn.com"
                f" iframe.mediadelivery.net"
                f" *.youtube.com"
                f" *.youtube-nocookie.com;",
                # KIM BIZNI iframe'lay oladi: o'zimiz + Telegram Web [P10-T1]
                "frame-ancestors 'self'"
                " https://web.telegram.org"
                " https://webk.telegram.org"
                " https://webz.telegram.org;",
                # Web Worker (HLS.js worker ishlatadi)
                "worker-src 'self' blob:;",
                # Object/embed teglari — yopilgan
                "object-src 'none';",
                # Base tegin o'zgartirishdan himoya
                "base-uri 'self';",
                # Forma submit — faqat o'zimizga
                "form-action 'self';",
            ]
        )

    def __call__(self, request):
        response = self.get_response(request)

        # Content-Security-Policy
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = self.csp

        # Permissions-Policy — keraksiz brauzer APIlarini o'chiradi
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(), "
                "payment=(), usb=(), gyroscope=(), "
                "accelerometer=(), magnetometer=()"
            )

        # Cross-Origin-Resource-Policy
        if "Cross-Origin-Resource-Policy" not in response:
            response["Cross-Origin-Resource-Policy"] = "cross-origin"

        # Referrer-Policy (HTTP header sifatida)
        if "Referrer-Policy" not in response:
            response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # X-XSS-Protection ATAYIN yuborilmaydi [P10-T1]: header deprecated,
        # eski brauzerlarda XSS Auditor'ni suiiste'mol qilish xavfi bor edi.

        return response
