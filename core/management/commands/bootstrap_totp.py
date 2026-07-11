"""bootstrap_totp — birinchi TOTP qurilma: admin 2FA'ga kirish eshigi [P10-T4].

ADMIN_REQUIRE_2FA yoqiq muhitda qurilmasiz staff /admin/ ga kira olmaydi;
bu buyruq authenticator ilovaga qo'shish uchun otpauth:// URL beradi.
Idempotent: tasdiqlangan qurilma bo'lsa yangisini ochmaydi, mavjudini chiqaradi.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Foydalanuvchiga tasdiqlangan TOTP qurilma yaratadi (admin 2FA)"

    def add_arguments(self, parser):
        parser.add_argument("username", help="Qurilma ochiladigan foydalanuvchi")

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=options["username"])
        except user_model.DoesNotExist as exc:
            raise CommandError(f"Foydalanuvchi topilmadi: {options['username']}") from exc

        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if device is None:
            device = TOTPDevice.objects.create(user=user, name="asosiy", confirmed=True)
            self.stdout.write(self.style.SUCCESS(f"Yangi TOTP qurilma yaratildi: {user.username}"))
        else:
            self.stdout.write(f"Mavjud tasdiqlangan qurilma: {device.name}")
        self.stdout.write("Quyidagi havolani authenticator ilovaga qo'shing:")
        self.stdout.write(device.config_url)
