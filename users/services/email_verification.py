"""users/services/email_verification.py — email tasdiqlash [P6-T1].

Saqlash: allauth EmailAddress jadvali — allauth INSTALLED_APPS'da (jadval mavjud,
yangi migratsiya kerak emas) va P6-T2 social login ham SHU jadvalga yozadi.
Oqim esa maxsus (allauth view'lari ulanmagan): kalit django.core.signing
(HMAC + muddat, DB'da saqlanmaydi) — parol tiklash tokeni bilan bir xil pattern.

"Tasdiqlangan" holat (user, JORIY user.email) juftligiga qaraydi — email
o'zgarsa (admin orqali bo'lsa ham) yangi juftlik uchun yozuv yo'q, holat
avtomatik "tasdiqlanmagan"ga tushadi; alohida reset-mantiq kerak emas.
"""

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.urls import reverse

from core.tasks import send_email_task

_SALT = "users.email-verification"
KEY_MAX_AGE = 3 * 24 * 3600  # havola 3 kun amal qiladi


def is_verified(user: User) -> bool:
    """Foydalanuvchining JORIY emaili tasdiqlanganmi."""
    if not user.email:
        return False
    return EmailAddress.objects.filter(user=user, email__iexact=user.email, verified=True).exists()


def make_key(email_address: EmailAddress) -> str:
    """Imzolangan (HMAC) tasdiqlash kaliti — email ham imzo ichida."""
    return signing.dumps({"pk": email_address.pk, "email": email_address.email}, salt=_SALT)


def confirm_key(key: str) -> EmailAddress | None:
    """Kalitni tekshirib EmailAddress'ni tasdiqlaydi; yaroqsiz/eskirgan -> None."""
    try:
        data = signing.loads(key, salt=_SALT, max_age=KEY_MAX_AGE)
    except signing.BadSignature:
        return None
    email_address = EmailAddress.objects.filter(
        pk=data.get("pk"), email__iexact=data.get("email", "")
    ).first()
    if email_address is None:
        return None
    if not email_address.verified:
        email_address.verified = True
        try:
            email_address.save(update_fields=["verified"])
        except IntegrityError:
            # Legacy dublikat: shu email boshqa hisobda allaqachon tasdiqlangan
            # (allauth unique_verified_email cheklovi) — havola yaroqsiz sanaladi.
            return None
    return email_address


def send_verification_email(user: User, request: HttpRequest) -> None:
    """Tasdiqlash havolasini fon (Celery)da yuboradi; email bo'sh bo'lsa skip.

    Chaqiruvchi transaksiya ichida bo'lishi mumkin — yuborish on_commit'da
    (user/EmailAddress qatorlari commit bo'lmaguncha worker ishga tushmasligi uchun).
    """
    if not user.email:
        return
    email_address = EmailAddress.objects.filter(user=user, email__iexact=user.email).first()
    if email_address is None:
        email_address = EmailAddress.objects.create(user=user, email=user.email)
    url = request.build_absolute_uri(reverse("users:verify_email", args=[make_key(email_address)]))
    subject = "Drama.uz — email manzilingizni tasdiqlang"
    body = (
        f"Assalomu alaykum, {user.username}!\n\n"
        f"Email manzilingizni tasdiqlash uchun quyidagi havolani bosing "
        f"(havola {KEY_MAX_AGE // 86400} kun amal qiladi):\n\n{url}\n\n"
        "Agar bu siz bo'lmasangiz, bu xatni e'tiborsiz qoldiring.\n\n"
        "Drama.uz jamoasi"
    )
    recipient = user.email
    transaction.on_commit(lambda: send_email_task.delay(subject, body, [recipient]))
