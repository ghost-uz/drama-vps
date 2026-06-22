"""Health / readiness endpointlari — monitoring va Docker healthcheck uchun.

- /healthz : liveness — yengil, hech narsani tekshirmaydi (process tirikmi).
- /readyz  : readiness — DB + Redis (cache) + migratsiyalar. Muammoda 503.
"""

from django.core.cache import cache
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness probe — process javob beradimi (yengil, bog'liqliksiz)."""
    return JsonResponse({"status": "ok"})


@never_cache
def readyz(request: HttpRequest) -> JsonResponse:
    """Readiness probe — barcha bog'liqliklar tayyormi. Muammoda 503."""
    checks: dict[str, str] = {}
    healthy = True

    # --- Ma'lumotlar bazasi ---
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
        healthy = False

    # --- Redis (cache) ---
    # IGNORE_EXCEPTIONS=True bo'lgani uchun qiymatni solishtirib tekshiramiz.
    try:
        cache.set("readyz:probe", "1", 5)
        checks["cache"] = "ok" if cache.get("readyz:probe") == "1" else "down"
    except Exception:
        checks["cache"] = "down"
    if checks["cache"] != "ok":
        healthy = False

    # --- Qo'llanilmagan migratsiyalar ---
    try:
        executor = MigrationExecutor(connections["default"])
        targets = executor.loader.graph.leaf_nodes()
        pending = executor.migration_plan(targets)
        checks["migrations"] = "ok" if not pending else "pending"
        if pending:
            healthy = False
    except Exception:
        checks["migrations"] = "error"
        healthy = False

    return JsonResponse(
        {"status": "ready" if healthy else "not_ready", "checks": checks},
        status=200 if healthy else 503,
    )
