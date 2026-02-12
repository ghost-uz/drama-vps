import os
from io import BytesIO
from PIL import Image
from datetime import datetime, date

from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.files.base import ContentFile

def movie_poster_path(instance, filename):
    """
    Eski migratsiyalar uchun saqlab qolindi. 
    Yangi fayllar save() metodidagi optimize_image orqali boshqariladi.
    """
    ext = filename.split('.')[-1]
    name = slugify(instance.title if hasattr(instance, 'title') else "poster")
    return f"movies/{name}.{ext}"
# --- Universal Optimizatsiya Funksiyasi ---
def optimize_image(image_field, filename_base):
    if not image_field or not hasattr(image_field, 'file'):
        return image_field

    img = Image.open(image_field)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    max_size = (1280, 1280)
    img.thumbnail(max_size, Image.LANCZOS)

    output = BytesIO()
    img.save(output, format='WEBP', quality=85)
    output.seek(0)

    # filename_base sifatida endi self.slug kelyapti
    new_filename = f"{filename_base}.webp"
    
    return ContentFile(output.read(), name=new_filename)

# --- Abstract Model ---
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Yaratilgan vaqti", auto_now_add=True)
    updated_at = models.DateTimeField("O'zgartirilgan vaqti", auto_now=True)

    class Meta:
        abstract = True

# --- Yordamchi Modellar ---

class Category(models.Model):
    name = models.CharField("Kategoriya nomi", max_length=150)
    description = models.TextField("Tavsif", blank=True)
    slug = models.SlugField(max_length=160, unique=True, db_index=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("drama:movie_list") + f"?category={self.id}"

    def __str__(self):
        return self.name

class Genre(models.Model):
    name = models.CharField("Janr nomi", max_length=100)
    description = models.TextField("Tavsif", blank=True)
    slug = models.SlugField(max_length=160, unique=True, db_index=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
         return reverse("drama:genre_detail", kwargs={"slug": self.slug})

    class Meta:
        verbose_name = "Janr"
        verbose_name_plural = "Janrlar"

class Actor(models.Model):
    GENDER_CHOICES = (('male', 'Erkak'), ('female', 'Ayol'))
    name = models.CharField("Ism Familiya", max_length=150)
    original_name = models.CharField("Asl ismi (Native)", max_length=150, blank=True)
    description = models.TextField("Biografiya", blank=True)
    image = models.ImageField("Rasmi", upload_to="actors/")
    birth_date = models.DateField("Tug'ilgan sanasi", default=date.today)
    birth_place = models.CharField("Tug'ilgan joyi", max_length=100, blank=True)
    gender = models.CharField("Jinsi", max_length=10, choices=GENDER_CHOICES, default='male')
    slug = models.SlugField(max_length=160, unique=True, db_index=True)

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return 0

    def save(self, *args, **kwargs):
        # 1. Avval slugni yaratamiz
        if not self.slug:
            self.slug = slugify(self.name)

        # 2. Rasmga slug orqali nom beramiz
        if self.image and hasattr(self.image, 'file'):
            self.image = optimize_image(self.image, self.slug)
            
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('drama:actor_detail', kwargs={"slug": self.slug})

    def __str__(self):
        return self.name

class TopSlider(models.Model):
    name = models.CharField("Slayder nomi", max_length=100, null=True)
    rank = models.CharField("Rank matni", max_length=50)
    image = models.ImageField("Slayder rasmi", upload_to="sliders/")
    target_url = models.URLField("Yo'naltiriluvchi URL", blank=True)

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'file'):
            self.image = optimize_image(self.image, self.name or "slider")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or "Slayder"

# --- Asosiy Film Modeli ---

class Movie(TimeStampedModel):
    title = models.CharField("Film nomi (Qidiruv uchun)", max_length=255, db_index=True)
    original_title = models.CharField("Original nomi (Kdrama)", max_length=255, blank=True)
    is_vip = models.BooleanField(default=False)
    tagline = models.CharField("Slogan", max_length=255, blank=True)
    description = models.TextField("Tavsif")
    poster = models.ImageField("Rasmi", upload_to='movies/')
    keywords = models.CharField("Meta Keywords", max_length=255, default='drama, kdrama', help_text="Vergul bilan ajrating")
    year = models.PositiveSmallIntegerField("Yili", default=2024)
    country = models.CharField("Davlat", max_length=50)
    duration = models.PositiveIntegerField("Davomiyligi (daqiqada)", default=60)
    episodes_count = models.PositiveIntegerField("Qismlar soni", default=16)
    age_limit = models.PositiveIntegerField("Yosh chegarasi", default=18)
    film_embed_code = models.TextField("Film HTML kodi", blank=True, default="<div>...</div>") 
    trailer_embed_code = models.TextField("Trailer HTML kodi", blank=True)
    site_rank = models.IntegerField("Sayt reytingi (Ichki)", default=0)
    mdl_rank = models.DecimalField("MyDramaList Reytingi", max_digits=4, decimal_places=1, default=0.0)
    main_actors = models.ManyToManyField(Actor, related_name="main_acted_movies")
    actors = models.ManyToManyField(Actor, related_name="acted_movies")
    genres = models.ManyToManyField(Genre)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name="movies")
    slug = models.SlugField(max_length=160, unique=True)
    is_draft = models.BooleanField("Qoralama (Draft)", default=False)
    
    def save(self, *args, **kwargs):
        # 1. Avval slugni yaratib olamiz (agar bo'sh bo'lsa)
        if not self.slug:
            self.slug = slugify(self.title)
        
        # 2. Endi rasmni optimallashtirishga aynan slugni beramiz
        if self.poster and hasattr(self.poster, 'file'):
            # self.title o'rniga self.slug uzatilyapti
            self.poster = optimize_image(self.poster, self.slug)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("drama:movie_detail", kwargs={"slug": self.slug})

class Episode(TimeStampedModel):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="episodes")
    title = models.CharField("Qism nomi", max_length=150)
    episode_number = models.PositiveIntegerField("Qism raqami")
    video_embed_code = models.TextField("Video HTML kodi (Embed)")
    thumbnail = models.ImageField("Qism uchun rasm", upload_to="episodes/", blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.thumbnail and hasattr(self.thumbnail, 'file'):
            name_base = f"{self.movie.title}-ep-{self.episode_number}"
            self.thumbnail = optimize_image(self.thumbnail, name_base)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.movie.title} - {self.episode_number}-qism"

class MovieShots(models.Model):
    title = models.CharField("Sarlavha", max_length=100)
    description = models.TextField("Tavsif", blank=True)
    image = models.ImageField("Rasm", upload_to="movie_shots/")
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="shots")

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'file'):
            name_base = f"{self.movie.title}-shot-{self.id or 'new'}"
            self.image = optimize_image(self.image, name_base)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

# --- Reyting va Izoh Modellarida o'zgarish yo'q ---
class RatingStar(models.Model):
    value = models.PositiveSmallIntegerField("Qiymat", default=0)
    def __str__(self): return str(self.value)

class Rating(models.Model):
    ip = models.GenericIPAddressField("IP Manzil")
    star = models.ForeignKey(RatingStar, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="ratings")

class Review(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="reviews")
    text = models.TextField("Izoh matni", max_length=5000)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name="replies")