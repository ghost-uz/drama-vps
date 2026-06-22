from django.conf import settings


class SecurityHeadersMiddleware:
    """
    Yetishmayotgan xavfsizlik sarlavhalarini qo'shadi:
    CSP, Permissions-Policy, X-XSS-Protection, CORP, Referrer-Policy (HTTP).
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
                # Skriptlar: o'zimiz + CDN + Yandex Metrika + inline (ko'p inline JS bor)
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
                " cdn.jsdelivr.net"
                " cdnjs.cloudflare.com"
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
                # iframe (video embed + Telegram uchun ochiq)
                f"frame-src 'self'"
                f" {bunny_cdn}"
                f" *.bunnycdn.com"
                f" iframe.mediadelivery.net"
                f" *.youtube.com"
                f" *.youtube-nocookie.com;",
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

        # X-XSS-Protection — eski brauzerlar uchun
        if "X-XSS-Protection" not in response:
            response["X-XSS-Protection"] = "1; mode=block"

        # Cross-Origin-Resource-Policy
        if "Cross-Origin-Resource-Policy" not in response:
            response["Cross-Origin-Resource-Policy"] = "cross-origin"

        # Referrer-Policy (HTTP header sifatida)
        if "Referrer-Policy" not in response:
            response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response
