# users/models.py
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.images import ImageOptimizationMixin


class Profile(ImageOptimizationMixin, models.Model):
    OPTIMIZE_IMAGE_FIELDS = {"avatar": {"max_size": (400, 400), "quality": 75}}

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    # ✅ Faqat bitta M2M yetarli (following orqali followers ni ham olamiz)
    following = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="followers",  # person.profile.followers → kim follow qilganlar
        blank=True,
    )
    avatar = models.ImageField(
        default="profile_pics/default.jpg", upload_to="profile_pics", null=True, blank=True
    )
    bio = models.TextField(max_length=500, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    telegram_id = models.CharField(max_length=30, null=True, blank=True)
    xp = models.PositiveIntegerField(default=0)
    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)
    # IntegerField (PositiveIntegerField emas): admin tasdiqni bekor qilganda
    # (coin allaqachon sarflangan bo'lsa) balans manfiy = "qarzdor" bo'lishi mumkin.
    # Ledger invarianti (balance == SUM(amount)) shu tufayli har doim saqlanadi.
    balance = models.IntegerField(default=0, verbose_name="Balans (Point)")

    # Avatar siqish ImageOptimizationMixin.save() orqali fon (Celery)da bajariladi.
    # default.jpg storage'dagi committed fayl — yangi yuklanmagani uchun siqilmaydi.

    @property
    def is_currently_premium(self):
        from django.utils import timezone

        if self.is_premium and self.premium_until:
            return self.premium_until > timezone.now()
        return self.is_premium

    @property
    def level(self):
        return (self.xp // 1000) + 1

    @property
    def progress_percent(self):
        return (self.xp % 1000) / 10

    def __str__(self):
        return f"{self.user.username} profili"


class UserMovieList(models.Model):
    STATUS_CHOICES = [
        (1, "Hozirda ko'ryapman"),
        (2, "Ko'rib tugallangan"),
        (3, "Ko'rish rejamda bor"),
        (4, "Ko'rish to'xtatilgan"),
        (5, "Menga qiziq emas"),
    ]

    # User o'rniga bevosita Profile ga bog'laymiz
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="movie_list")
    movie = models.ForeignKey("drama.Movie", on_delete=models.CASCADE)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES)

    # Qismlar va Baholash (Faqat 1, 2, 4 statuslar uchun mantiqan to'g'ri)
    current_episode = models.PositiveIntegerField(default=0)
    score = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(1.0), MaxValueValidator(10.0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("profile", "movie")  # Bir profil bitta kinoni qayta qo'sholmaydi
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.profile.user.username} - {self.movie.title}"


class TopUpRequest(models.Model):
    STATUS_CHOICES = (
        ("pending", "Kutilmoqda"),
        ("approved", "Tasdiqlandi"),
        ("rejected", "Rad etildi"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="topup_requests")
    amount_uzs = models.PositiveIntegerField(verbose_name="To'lov summasi (UZS)")
    points = models.PositiveIntegerField(verbose_name="Beriladigan Pointlar", blank=True, null=True)
    receipt_image = models.ImageField(upload_to="receipts/%Y/%m/", verbose_name="To'lov cheki")
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default="pending", verbose_name="Holati"
    )
    admin_note = models.TextField(blank=True, null=True, verbose_name="Admin izohi (rad etilsa)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hisob to'ldirish so'rovi"
        verbose_name_plural = "Hisob to'ldirish so'rovlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.amount_uzs} UZS ({self.get_status_display()})"

    def clean(self):
        # 1-QOIDA: Agar user biriktirilgan bo'lsagina bazani tekshiramiz!
        # getattr(self, 'user_id', None) orqali xavfsiz murojaat qilamiz.
        if self.status == "pending" and not self.pk and getattr(self, "user_id", None):
            has_pending = TopUpRequest.objects.filter(user=self.user, status="pending").exists()
            if has_pending:
                raise ValidationError(
                    "Sizda allaqachon kutilayotgan so'rov mavjud. Iltimos, admin tasdiqlashini kuting."
                )

    def save(self, *args, **kwargs):
        # 2-QOIDA: Pointlarni avtomat hisoblash (1,000 UZS = 1 Coin)
        if not self.points:
            self.points = self.amount_uzs // 1000

        # 3-QOIDA: Admin tasdiqlasa, profilga pulni o'tkazish
        # FIX: select_for_update() — race condition va double-credit oldini olish
        if self.pk:
            try:
                old_record = TopUpRequest.objects.get(pk=self.pk)
            except TopUpRequest.DoesNotExist:
                old_record = None

            if old_record:
                from users.services import wallet

                # Tasdiqlash: ledger orqali kredit (atomik + audit izi)
                if old_record.status == "pending" and self.status == "approved":
                    wallet.credit(
                        self.user.profile,
                        self.points,
                        CoinTransaction.Type.TOPUP,
                        description=f"Hisob to'ldirish #{self.pk} ({self.amount_uzs} UZS)",
                        reference=f"topup:{self.pk}",
                    )

                # Tasdiq bekor qilindi: debet (coin sarflangan bo'lsa manfiyga ruxsat)
                elif old_record.status == "approved" and self.status in ["pending", "rejected"]:
                    wallet.debit(
                        self.user.profile,
                        self.points,
                        CoinTransaction.Type.REFUND,
                        description=f"Hisob to'ldirish #{self.pk} tasdig'i bekor qilindi",
                        reference=f"topup:{self.pk}",
                        allow_negative=True,
                    )

        super().save(*args, **kwargs)


class CryptoTopUpRequest(models.Model):
    STATUS_CHOICES = (
        ("pending", "Kutilmoqda"),
        ("approved", "Tasdiqlandi"),
        ("rejected", "Rad etildi"),
    )

    USDT_TO_COIN = 12  # 1 USDT = 12 Coin

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="crypto_topup_requests")
    amount_usdt = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="To'lov summasi (USDT)"
    )
    points = models.PositiveIntegerField(verbose_name="Beriladigan Coinlar", blank=True, null=True)
    receipt_image = models.ImageField(
        upload_to="crypto_receipts/%Y/%m/", verbose_name="To'lov skrinshotı"
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default="pending", verbose_name="Holati"
    )
    admin_note = models.TextField(blank=True, null=True, verbose_name="Admin izohi (rad etilsa)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kripto to'ldirish so'rovi"
        verbose_name_plural = "Kripto to'ldirish so'rovlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.amount_usdt} USDT ({self.get_status_display()})"

    def clean(self):
        if self.status == "pending" and not self.pk and getattr(self, "user_id", None):
            has_pending = CryptoTopUpRequest.objects.filter(
                user=self.user, status="pending"
            ).exists()
            if has_pending:
                raise ValidationError("Sizda allaqachon kutilayotgan kripto so'rov mavjud.")

    def save(self, *args, **kwargs):
        if not self.points:
            self.points = int(float(self.amount_usdt) * self.USDT_TO_COIN)

        if self.pk:
            try:
                old_record = CryptoTopUpRequest.objects.get(pk=self.pk)
            except CryptoTopUpRequest.DoesNotExist:
                old_record = None

            if old_record:
                from users.services import wallet

                if old_record.status == "pending" and self.status == "approved":
                    wallet.credit(
                        self.user.profile,
                        self.points,
                        CoinTransaction.Type.CRYPTO_TOPUP,
                        description=f"Kripto to'ldirish #{self.pk} ({self.amount_usdt} USDT)",
                        reference=f"crypto_topup:{self.pk}",
                    )

                elif old_record.status == "approved" and self.status in ["pending", "rejected"]:
                    wallet.debit(
                        self.user.profile,
                        self.points,
                        CoinTransaction.Type.REFUND,
                        description=f"Kripto to'ldirish #{self.pk} tasdig'i bekor qilindi",
                        reference=f"crypto_topup:{self.pk}",
                        allow_negative=True,
                    )

        super().save(*args, **kwargs)


class WatchProgress(models.Model):
    """Foydalanuvchining qism bo'yicha ko'rish progressi ('davom ettirish')."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watch_progress")
    episode = models.ForeignKey(
        "drama.Episode", on_delete=models.CASCADE, related_name="watch_progress"
    )
    position_seconds = models.PositiveIntegerField("Pozitsiya (sekund)", default=0)
    duration_seconds = models.PositiveIntegerField("Davomiyligi (sekund)", default=0)
    completed = models.BooleanField("Ko'rib tugatilgan", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "episode")
        # (user, -updated_at): 'davom ettirish' ro'yxatini tez oladi
        indexes = [models.Index(fields=["user", "-updated_at"])]
        ordering = ["-updated_at"]
        verbose_name = "Ko'rish progressi"
        verbose_name_plural = "Ko'rish progresslari"

    @property
    def percent(self) -> int:
        if self.duration_seconds:
            return min(round(self.position_seconds / self.duration_seconds * 100), 100)
        return 0

    def __str__(self):
        return f"{self.user.username} - {self.episode} ({self.percent}%)"


class CoinTransaction(models.Model):
    """Coin hamyon ledgeri — har bir balans harakatining o'zgarmas yozuvi.

    Invariant: ``profile.balance == SUM(amount)``. ``balance_after`` har
    yozuvdan keyingi balans (sverka/audit uchun). Yozuvlar o'zgartirilmaydi.
    Yagona yozuvchi: ``users.services.wallet`` (credit/debit).
    """

    class Type(models.TextChoices):
        OPENING = "opening", "Boshlang'ich balans"
        TOPUP = "topup", "Hisob to'ldirish"
        CRYPTO_TOPUP = "crypto_topup", "Kripto to'ldirish"
        GIFT = "gift", "Aktyorga sovg'a"
        FUNDING = "funding", "Crowdfunding hissa"
        VIP = "vip", "VIP obuna"
        REFUND = "refund", "Qaytarish"
        ADJUSTMENT = "adjustment", "Admin tuzatishi"

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="coin_transactions")
    amount = models.IntegerField("Miqdor (+kredit / -debet)")
    type = models.CharField("Turi", max_length=20, choices=Type.choices)
    balance_after = models.IntegerField("Yozuvdan keyingi balans")
    description = models.CharField("Izoh", max_length=255, blank=True)
    reference = models.CharField("Manba (model:id)", max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # (-created_at, -id): bir soniyada bir nechta yozuvni ham aniq tartiblaydi
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["profile", "-created_at"])]
        verbose_name = "Coin tranzaksiyasi"
        verbose_name_plural = "Coin tranzaksiyalari"

    def __str__(self):
        sign = "+" if self.amount >= 0 else ""
        return f"{self.profile.user.username}: {sign}{self.amount} ({self.get_type_display()})"
