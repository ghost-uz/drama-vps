"""core/audit.py — muhim amallar audit jurnali [P10-T4].

Foydalanish (admin action ichida):

    from core import audit
    audit.log(request.user, "topup.approve", f"TopUpRequest#{req.pk}",
              details=f"{req.user.username} +{req.points} coin", request=request)

Yozuv o'zgarmas — "kim, nima, qachon" savoliga ishonchli javob. IP mijozning
haqiqiy manzili (Cloudflare-aware core.http.client_ip).
"""

from __future__ import annotations

from core.http import client_ip
from core.models import AuditLog


def log(actor, action: str, target: str = "", *, details: str = "", request=None) -> AuditLog:
    """Bitta audit yozuvi yaratadi; anonim actor None sifatida saqlanadi."""
    ip = client_ip(request) if request is not None else None
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        actor=actor, action=action, target=target[:200], details=details[:500], ip=ip
    )
