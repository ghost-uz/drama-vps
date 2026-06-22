"""drama app fon vazifalari — Celery autodiscover shu fayldan topadi.

Hozircha skelet (P3 da rasm-siqish, Bunny upload, rating qayta hisoblash qo'shiladi).
"""

from celery import shared_task


@shared_task
def add(x: int, y: int) -> int:
    """Skelet test task — autodiscover va result-backend'ni tasdiqlaydi."""
    return x + y


@shared_task
def ping() -> str:
    return "pong"
