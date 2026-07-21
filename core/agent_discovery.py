"""Agent-discovery indeksi [DNS-AID] — /.well-known/agent-index.json.

DNS-AID (draft-mozleywilliams-dnsop-dnsaid) `_index._agents.drama.uz` SVCB
yozuvi agentlarni shu hostga yo'naltiradi; ular esa bu yerdan mashina-o'qiydigan
xizmat xaritasini oladi (well-known entrypoint, RFC 8615).

MUHIM (halollik): drama.uz avtonom agent protokolini (A2A/MCP) YURITMAYDI —
u ommaviy REST API + OpenAPI taqdim etadi. Shu sabab bu hujjat "agent-card" EMAS,
balki mavjud mashina-o'qiydigan resurslarning ROSTGO'Y indeksi:
  service-desc — OpenAPI sxemasi (mashina), service-doc — Swagger UI (inson).
Havolalar absolyut: hujjat mustaqil olinadi/saqlanadi (kontekstdan uzilgan), shu
bois to'liq URL kerak. prod'da https://drama.uz/... (SECURE_PROXY_SSL_HEADER
Cloudflare orqasida https sxemani, ALLOWED_HOSTS kanonik hostni kafolatlaydi).
"""

from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control


@cache_control(public=True, max_age=3600)
def agent_index(request: HttpRequest) -> JsonResponse:
    """Mashina-o'qiydigan xizmat indeksi (DNS-AID _index entrypoint backing doc)."""
    return JsonResponse(
        {
            "name": "Drama.uz",
            "description": (
                "drama.uz striming platformasi — ommaviy REST API va OpenAPI hujjatlari."
            ),
            "homepage": request.build_absolute_uri("/"),
            "services": [
                {
                    "rel": "service-desc",
                    "type": "application/vnd.oai.openapi+json",
                    "href": request.build_absolute_uri(reverse("api:schema")),
                    "description": "OpenAPI 3 sxemasi (mashina o'qiydigan API ta'rifi).",
                },
                {
                    "rel": "service-doc",
                    "type": "text/html",
                    "href": request.build_absolute_uri(reverse("api:docs")),
                    "description": "Swagger UI (inson o'qiydigan interaktiv hujjat).",
                },
            ],
        }
    )
