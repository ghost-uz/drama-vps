# users/models.py
import os
import time  # Cache busting uchun timestamp yaratishga kerak
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.core.exceptions import ValidationError


# --- Universal Optimizatsiya Funksiyasi ---
def optimize_avatar(image_field, username):
    if not image_field or not hasattr(image_field, 'file'):
        return image_field

    # 🌟 SENIOR FIX: InMemoryUploadedFile o'rniga UploadedFile ishlatsangiz, 
    # 3-5 MB li rasmlar ham xatosiz siqilib, saqlanadi!
    from django.core.files.uploadedfile import UploadedFile
    if not isinstance(image_field.file, UploadedFile):
        return image_field

    try:
        img = Image.open(image_field)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Avatar uchun 400x400 yetarli (hajmni tejash uchun)
        img.thumbnail((400, 400), Image.LANCZOS)

        output = BytesIO()
        img.save(output, format='WEBP', quality=75) # Avatar uchun 75% sifat ideal
        output.seek(0)
        
        timestamp = int(time.time() * 1000)
        new_filename = f"{slugify(username)}_{timestamp}.webp"
        
        return ContentFile(output.read(), name=new_filename)
    except Exception:
        return image_field

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # ✅ Faqat bitta M2M yetarli (following orqali followers ni ham olamiz)
    following = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='followers',  # person.profile.followers → kim follow qilganlar
        blank=True
    )
    avatar = models.ImageField(default='profile_pics/default.jpg', upload_to='profile_pics', null=True, blank=True)
    bio = models.TextField(max_length=500, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    telegram_id = models.CharField(max_length=30, null=True, blank=True)
    xp = models.PositiveIntegerField(default=0)
    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)
    balance = models.PositiveIntegerField(default=0, verbose_name="Balans (Point)")

    def save(self, *args, **kwargs):
        # 1. Agar profil yangi bo'lsa
        if not self.pk:
            if self.avatar and 'default.jpg' not in self.avatar.name:
                self.avatar = optimize_avatar(self.avatar, self.user.username)
        else:
            # 2. Agar mavjud profil tahrirlanayotgan bo'lsa
            try:
                old_instance = Profile.objects.get(pk=self.pk)
                # Faqat rasm o'zgargan bo'lsa optimallashtiramiz
                if old_instance.avatar != self.avatar and self.avatar:
                     if 'default.jpg' not in self.avatar.name:
                        self.avatar = optimize_avatar(self.avatar, self.user.username)
            except Profile.DoesNotExist:
                pass
        
        super().save(*args, **kwargs)

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
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='movie_list')
    movie = models.ForeignKey('drama.Movie', on_delete=models.CASCADE) 
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES)
    
    # Qismlar va Baholash (Faqat 1, 2, 4 statuslar uchun mantiqan to'g'ri)
    current_episode = models.PositiveIntegerField(default=0)
    score = models.DecimalField(
        max_digits=3, decimal_places=1, 
        null=True, blank=True,
        validators=[MinValueValidator(1.0), MaxValueValidator(10.0)]
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('profile', 'movie') # Bir profil bitta kinoni qayta qo'sholmaydi
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.profile.user.username} - {self.movie.title}"



class TopUpRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('approved', 'Tasdiqlandi'),
        ('rejected', 'Rad etildi'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='topup_requests')
    amount_uzs = models.PositiveIntegerField(verbose_name="To'lov summasi (UZS)")
    points = models.PositiveIntegerField(verbose_name="Beriladigan Pointlar", blank=True, null=True)
    receipt_image = models.ImageField(upload_to='receipts/%Y/%m/', verbose_name="To'lov cheki")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending', verbose_name="Holati")
    admin_note = models.TextField(blank=True, null=True, verbose_name="Admin izohi (rad etilsa)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hisob to'ldirish so'rovi"
        verbose_name_plural = "Hisob to'ldirish so'rovlari"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.amount_uzs} UZS ({self.get_status_display()})"

    def clean(self):
        # 1-QOIDA: Agar user biriktirilgan bo'lsagina bazani tekshiramiz!
        # getattr(self, 'user_id', None) orqali xavfsiz murojaat qilamiz.
        if self.status == 'pending' and not self.pk and getattr(self, 'user_id', None):
            has_pending = TopUpRequest.objects.filter(user=self.user, status='pending').exists()
            if has_pending:
                raise ValidationError("Sizda allaqachon kutilayotgan so'rov mavjud. Iltimos, admin tasdiqlashini kuting.")

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
                from django.db import transaction as db_transaction

                # Tasdiqlash: balance qo'shish
                if old_record.status == 'pending' and self.status == 'approved':
                    with db_transaction.atomic():
                        # select_for_update — parallel so'rovlar balance ni 2x qo'shib yubormasligi uchun
                        profile = Profile.objects.select_for_update().get(pk=self.user.profile.pk)
                        profile.balance += self.points
                        profile.save(update_fields=['balance'])

                # Orqaga qaytarish: balance ayirish
                elif old_record.status == 'approved' and self.status in ['pending', 'rejected']:
                    with db_transaction.atomic():
                        profile = Profile.objects.select_for_update().get(pk=self.user.profile.pk)
                        if profile.balance >= self.points:
                            profile.balance -= self.points
                            profile.save(update_fields=['balance'])

        super().save(*args, **kwargs)