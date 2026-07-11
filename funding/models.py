"""funding/models.py — crowdfunding (tarjima loyihalari) [P7-T4 hardening].

Pul oqimi invarianti: hissa va refund Coin harakati FAQAT
users/services/wallet.py ledgeri orqali; bu yerdagi collected_amount —
ko'rsatkich (denormal), haqiqat manbai emas. Holat o'tishlari (maqsadga
yetish -> TRANSLATING, bekor qilish -> CANCELED + ommaviy refund) faqat
funding/services.py orqali boshqariladi.
"""

from django.db import models

from drama.models import Movie
from users.models import Profile


class FundingProject(models.Model):
    """Bitta kino uchun tarjima-crowdfunding loyihasi."""

    class Status(models.TextChoices):
        FUNDING = "funding", "Pul yig'ilmoqda"
        TRANSLATING = "translating", "Tarjima jarayonida"
        RELEASED = "released", "Saytga chiqdi (Tayyor)"
        CANCELED = "canceled", "Bekor qilindi (refund)"

    movie = models.OneToOneField(Movie, on_delete=models.CASCADE, related_name="funding_project")
    target_amount = models.PositiveIntegerField(verbose_name="Yig'ilishi kerak bo'lgan jami Coin")
    collected_amount = models.PositiveIntegerField(default=0, verbose_name="Hozirgacha yig'ildi")
    min_fund_amount = models.PositiveIntegerField(default=50, verbose_name="Minimal hissa (Coin)")
    post_release_price = models.PositiveIntegerField(
        default=100, verbose_name="Tayyor serial narxi (Coin)"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.FUNDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Funding loyihasi"
        verbose_name_plural = "Funding loyihalari"
        constraints = [
            # target=0 goal-transition va progress mantiqlarini ma'nosiz qilardi
            models.CheckConstraint(
                condition=models.Q(target_amount__gte=1),
                name="funding_target_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.movie.title} - {self.get_status_display()}"

    @property
    def progress_percentage(self):
        if self.target_amount == 0:
            return 0
        calc = (self.collected_amount / self.target_amount) * 100
        return min(calc, 100)

    def has_access(self, profile):
        """Refund qilinMAgan hissasi bor foydalanuvchigina kirish huquqiga ega."""
        return self.contributors.filter(profile=profile, refunded_at__isnull=True).exists()


class FundingContributor(models.Model):
    """Bitta hissa (bir foydalanuvchi bir loyihaga bir necha marta qo'sha oladi)."""

    project = models.ForeignKey(
        FundingProject, on_delete=models.CASCADE, related_name="contributors"
    )
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    amount_paid = models.PositiveIntegerField()
    funded_at = models.DateTimeField(auto_now_add=True)
    # Loyiha bekor qilinganda to'ldiriladi — refund IZI va idempotentlik kaliti:
    # belgilangan hissa ikkinchi marta qaytarilmaydi [P7-T4]
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name="Refund vaqti")

    class Meta:
        ordering = ["-funded_at"]
        indexes = [
            # has_access exists() va cancel-refund skani shu juftlik bo'yicha yuradi
            models.Index(fields=["project", "profile"], name="funding_contrib_proj_prof"),
        ]
        verbose_name = "Funding hissasi"
        verbose_name_plural = "Funding hissalari"

    def __str__(self):
        return f"{self.profile.user.username} -> {self.amount_paid} Coin"
