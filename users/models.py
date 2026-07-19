# users/models.py
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from core.images import ImageOptimizationMixin
from core.validators import ImageFileValidator, RandomFileName


def _send_topup_approved_email(user, points):
    """Topup tasdiqlanganda: ichki bildirishnoma + email [P3-T3 / P6-T3].

    Ichki bildirishnoma (kabinet markazi) emaildan OLDIN — emailsiz Telegram
    foydalanuvchilari ham xabar oladi.
    """
    from functools import partial

    from django.db import transaction
    from django.urls import reverse

    from core.tasks import send_email_task
    from users.services import notifications as notif

    notif.notify(
        user,
        Notification.Kind.TOPUP,
        "Hisobingiz to'ldirildi",
        body=f"{points} Coin qo'shildi. Yoqimli tomosha!",
        url=reverse("users:transactions"),
    )
    if not user.email:
        return

    transaction.on_commit(
        partial(
            send_email_task.delay,
            "Drama.uz — hisobingiz to'ldirildi",
            f"Assalomu alaykum! Hisobingizga {points} Coin qo'shildi. Yoqimli tomosha!",
            [user.email],
        )
    )


class Profile(ImageOptimizationMixin, models.Model):
    OPTIMIZE_IMAGE_FIELDS = {"avatar": {"max_size": (400, 400), "quality": 75}}

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    # ✅ Faqat bitta M2M yetarli (following orqali followers ni ham olamiz)
    following = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="followers",  # person.profile.followers → kim follow qilganlar
        blank=True,
    )
    avatar = models.ImageField(
        default="profile_pics/default.jpg",
        upload_to=RandomFileName("profile_pics"),
        null=True,
        blank=True,
        validators=[ImageFileValidator(max_mb=5)],
    )
    bio = models.TextField(max_length=500, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    telegram_id = models.CharField(max_length=30, null=True, blank=True)
    # Bildirishnoma sozlamalari [V2A-T1] — per-kanal opt-out. Telegram kanalini
    # V2A-T2 (foydalanuvchi boti) ishlatadi; sxema oldindan tayyor.
    notify_new_episode = models.BooleanField(
        "Yangi qism chiqqanda xabar berish (saytda)", default=True
    )
    notify_new_episode_telegram = models.BooleanField(
        "Yangi qism chiqqanda xabar berish (Telegram)", default=True
    )
    # [V2A-T2] Bot orqali TASDIQLANGAN shaxsiy chat — deep-link /start'da yoziladi.
    # Erkin telegram_id (matn)dan farqi: bunga yozish MUMKINLIGI kafolatlangan
    # (foydalanuvchi botda Start bosgan). Bot 403 qaytarsa tozalanadi.
    telegram_chat_id = models.BigIntegerField(
        "Telegram bot chat ID", null=True, blank=True, unique=True
    )
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
    # Nomlangan konstantalar [V2A-T1] — "sehrli son"larga murojaat o'rniga
    WATCHING = 1
    PLANNED = 3
    # Shu statuslar kino "kuzatuvi" hisoblanadi -> yangi qism xabari boradi
    FOLLOW_STATUSES = (WATCHING, PLANNED)

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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topup_requests"
    )
    amount_uzs = models.PositiveIntegerField(verbose_name="To'lov summasi (UZS)")
    points = models.PositiveIntegerField(verbose_name="Beriladigan Pointlar", blank=True, null=True)
    receipt_image = models.ImageField(
        upload_to=RandomFileName("receipts"),
        verbose_name="To'lov cheki",
        validators=[ImageFileValidator(max_mb=10)],
    )
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
                    _send_topup_approved_email(self.user, self.points)

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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crypto_topup_requests"
    )
    amount_usdt = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="To'lov summasi (USDT)"
    )
    points = models.PositiveIntegerField(verbose_name="Beriladigan Coinlar", blank=True, null=True)
    receipt_image = models.ImageField(
        upload_to=RandomFileName("crypto_receipts"),
        verbose_name="To'lov skrinshotı",
        validators=[ImageFileValidator(max_mb=10)],
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
                    _send_topup_approved_email(self.user, self.points)

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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watch_progress"
    )
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
        PAYME = "payme", "Payme to'lovi"
        CLICK = "click", "Click to'lovi"
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


class SubscriptionPlan(models.Model):
    """Obuna rejasi — admin boshqaradi [P7-T1].

    Reja o'chirilmaydi (Subscription.plan PROTECT) — sotuvdan olish uchun
    is_active=False qilinadi; tarixiy obunalar va ledger narxlari saqlanadi.
    """

    name = models.CharField("Nomi", max_length=100)
    price_coins = models.PositiveIntegerField("Narxi (Coin)")
    duration_days = models.PositiveIntegerField("Davomiyligi (kun)")
    perks = models.TextField("Imtiyozlar (har qatorda bittadan)", blank=True)
    is_active = models.BooleanField("Sotuvda", default=True)
    sort_order = models.PositiveSmallIntegerField("Tartib", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_coins"]
        verbose_name = "Obuna rejasi"
        verbose_name_plural = "Obuna rejalari"

    def __str__(self):
        return f"{self.name} — {self.price_coins} Coin / {self.duration_days} kun"

    @property
    def perks_list(self) -> list[str]:
        """Shablon uchun: perks matnini qatorlarga bo'lib beradi."""
        return [line.strip() for line in self.perks.splitlines() if line.strip()]


class Subscription(models.Model):
    """Foydalanuvchi obunasi — premium holatning HAQIQAT MANBAI [P7-T1].

    Profile.is_premium/premium_until KESH: gating (playback) va shablonlar
    O(1) o'qiydi; users/services/subscriptions.py har o'zgarishda sinxronlaydi.
    Obunasiz legacy premium (admin qo'lda bergan) o'z holicha ishlayveradi.
    end_at=None — muddatsiz (admin sovg'asi).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        EXPIRED = "expired", "Muddati tugagan"
        CANCELED = "canceled", "Bekor qilingan"

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    status = models.CharField(
        "Holati", max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    start_at = models.DateTimeField("Boshlanishi")
    end_at = models.DateTimeField("Tugashi", null=True, blank=True)
    auto_renew = models.BooleanField("Avto-uzaytirish (balansdan)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        # Beat sweep (status + end_at) tez ishlashi uchun
        indexes = [models.Index(fields=["status", "end_at"])]
        # Invariant: bitta profilda bir vaqtda faqat bitta ACTIVE obuna
        constraints = [
            models.UniqueConstraint(
                fields=["profile"],
                condition=models.Q(status="active"),
                name="unique_active_subscription_per_profile",
            )
        ]
        verbose_name = "Obuna"
        verbose_name_plural = "Obunalar"

    def __str__(self):
        return f"{self.profile.user.username} — {self.plan.name} ({self.get_status_display()})"


class Notification(models.Model):
    """Sayt ichidagi foydalanuvchi bildirishnomasi (kabinet markazi) [P6-T3].

    Tashqi kanallar (Telegram/email push) core/notifications.py'da — bu MODEL
    faqat SAYT ICHIDAGI o'qildi/o'qilmadi holatli ro'yxat. Yaratish yagona nuqtasi:
    users/services/notifications.py :: notify().
    """

    class Kind(models.TextChoices):
        SYSTEM = "system", "Tizim"
        TOPUP = "topup", "Hisob to'ldirildi"
        FOLLOW = "follow", "Yangi obunachi"
        SUBSCRIPTION = "subscription", "Obuna"
        NEW_EPISODE = "new_episode", "Yangi qism"
        REPLY = "reply", "Izohga javob"
        FUNDING = "funding", "Crowdfunding"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField("Turi", max_length=20, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField("Sarlavha", max_length=200)
    body = models.CharField("Matn", max_length=300, blank=True)
    url = models.CharField("Havola", max_length=300, blank=True)
    is_read = models.BooleanField("O'qilgan", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"


class Collection(models.Model):
    """Foydalanuvchi kolleksiyasi — ulashiladigan ro'yxat [V2B-T4].

    UserMovieList STATUS-asosli (ko'rmoqda/tugatdi...); bu esa ERKIN tanlov:
    nomlangan, tartiblangan, ixtiyoriy ommaviy (public URL + OG preview).
    """

    MAX_ITEMS = 100  # AC-1: bitta kolleksiyada eng ko'pi 100 element

    owner = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="collections")
    name = models.CharField("Nomi", max_length=100)
    slug = models.SlugField(max_length=120)
    description = models.TextField("Tavsif", max_length=1000, blank=True)
    is_public = models.BooleanField("Ommaviy", default=False)
    movies = models.ManyToManyField(
        "drama.Movie", through="CollectionItem", related_name="in_collections", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Public sahifa kesh-kaliti shu maydonga bog'liq: item qo'shish/o'chirish/
    # tartiblash M2M orqali — auto_now O'ZI ishlamaydi, view'lar qo'lda bump qiladi
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "slug"], name="uniq_collection_owner_slug")
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            # Kirill/emoji nomlarda slugify bo'sh qaytaradi -> tasodifiy fallback
            base = slugify(self.name)[:100] or f"toplam-{secrets.token_hex(4)}"
            slug = base
            n = 2
            while (
                Collection.objects.filter(owner=self.owner, slug=slug).exclude(pk=self.pk).exists()
            ):
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("users:collection_detail", args=[self.owner.user.username, self.slug])


class CollectionItem(models.Model):
    """Kolleksiya elementi [V2B-T4] — tartib (position) + ixtiyoriy izoh."""

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="items")
    movie = models.ForeignKey("drama.Movie", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)
    note = models.CharField("Izoh", max_length=200, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "movie"], name="uniq_collection_movie")
        ]
        ordering = ["position", "id"]
