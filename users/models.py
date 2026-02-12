import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify

# --- Universal Optimizatsiya Funksiyasi ---
def optimize_avatar(image_field, username):
    if not image_field or not hasattr(image_field, 'file'):
        return image_field

    # Agar rasm yangi yuklangan bo'lsa (InMemoryUploadedFile), uni qayta ishlaymiz
    from django.core.files.uploadedfile import InMemoryUploadedFile
    if not isinstance(image_field.file, InMemoryUploadedFile):
        return image_field

    img = Image.open(image_field)
    
    # RGBA (shaffof) rasmlarni RGB ga o'tkazish (WEBP va JPEG uchun shart)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Profil uchun kvadrat ko'rinishida thumbnail qilish
    # (500x500 profil uchun ideal o'lcham)
    img.thumbnail((500, 500), Image.LANCZOS)

    output = BytesIO()
    img.save(output, format='WEBP', quality=80) # Sifatni 80% qilish hajm va tiniqlik balansi
    output.seek(0)

    # Fayl nomi: username.webp
    new_filename = f"{slugify(username)}.webp"
    
    return ContentFile(output.read(), name=new_filename)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(default='profile_pics/default.jpg', upload_to='profile_pics', null=True, blank=True)
    bio = models.TextField(max_length=500, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    telegram_id = models.CharField(max_length=30, null=True, blank=True)
    xp = models.PositiveIntegerField(default=0)
    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Profil saqlanayotganda avatarni optimallashtirish
        if self.avatar:
            self.avatar = optimize_avatar(self.avatar, self.user.username)
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