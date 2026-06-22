from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from PIL import Image


def movie_poster_path(instance, filename):
    """
    Eski migratsiyalar uchun saqlab qolindi.
    Yangi fayllar save() metodidagi optimize_image orqali boshqariladi.
    """
    ext = filename.split(".")[-1]
    name = slugify(instance.title if hasattr(instance, "title") else "poster")
    return f"movies/{name}.{ext}"


# --- Universal Optimizatsiya Funksiyasi ---
def optimize_image(image_field, filename_base):
    # PIL jarayonini faqat kerak bo'lganda chaqirish uchun shart
    if not image_field or not hasattr(image_field, "file"):
        return image_field

    try:
        img = Image.open(image_field)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        max_size = (1280, 1280)
        img.thumbnail(max_size, Image.LANCZOS)

        output = BytesIO()
        img.save(output, format="WEBP", quality=80, optimize=True)  # quality 80 yetarli
        output.seek(0)

        return ContentFile(output.read(), name=f"{filename_base}.webp")
    except Exception as e:
        print(f"Rasmda xatolik: {e}")
        return image_field


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


# drama/models.py


class Tag(models.Model):
    name = models.CharField("Teg nomi", max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        verbose_name = "Teg"
        verbose_name_plural = "Teglar"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("drama:tag_detail", kwargs={"slug": self.slug})


class Actor(models.Model):
    GENDER_CHOICES = (("male", "Erkak"), ("female", "Ayol"))
    name = models.CharField("Ism Familiya", max_length=150)
    original_name = models.CharField("Asl ismi (Native)", max_length=150, blank=True)
    description = models.TextField("Biografiya", blank=True)
    image = models.ImageField("Rasmi", upload_to="actors/")
    birth_date = models.DateField("Tug'ilgan sanasi", default=date.today)
    birth_place = models.CharField("Tug'ilgan joyi", max_length=100, blank=True)
    gender = models.CharField("Jinsi", max_length=10, choices=GENDER_CHOICES, default="male")
    slug = models.SlugField(max_length=160, unique=True, db_index=True)
    total_gifts = models.PositiveIntegerField("Umumiy sovg'alar (Coin)", default=0)

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return (
                today.year
                - self.birth_date.year
                - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
            )
        return 0

    def save(self, *args, **kwargs):
        # 1. Avval slugni yaratamiz
        if not self.slug:
            self.slug = slugify(self.name)

        # 2. Rasmga slug orqali nom beramiz
        # Faqatgina yangi yaratilayotganda yoki rasm o'zgargandagina ishlasin
        if self.pk:
            try:
                old_actor = Actor.objects.get(pk=self.pk)
                if old_actor.image != self.image and self.image and hasattr(self.image, "file"):
                    self.image = optimize_image(self.image, self.slug)
            except Actor.DoesNotExist:
                pass
        else:
            if self.image and hasattr(self.image, "file"):
                self.image = optimize_image(self.image, self.slug)

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("drama:actor_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.name


class TopSlider(models.Model):
    name = models.CharField("Slayder nomi", max_length=100, null=True)
    rank = models.CharField("Rank matni", max_length=50)
    image = models.ImageField("Slayder rasmi", upload_to="sliders/")
    target_url = models.URLField("Yo'naltiriluvchi URL", blank=True)

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, "file"):
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
    poster = models.ImageField("Rasmi", upload_to="movies/")
    tags = models.ManyToManyField(Tag, related_name="movies", blank=True)
    year = models.PositiveSmallIntegerField("Yili", default=2024)
    country = models.CharField("Davlat", max_length=50)
    duration = models.PositiveIntegerField("Davomiyligi (daqiqada)", default=60)
    episodes_count = models.PositiveIntegerField("Qismlar soni", default=16)
    age_limit = models.PositiveIntegerField("Yosh chegarasi", default=18)
    bunny_video_id = models.CharField("Bunny Stream Video ID (Film)", max_length=100, blank=True)
    bunny_trailer_id = models.CharField(
        "Bunny Stream Video ID (Trailer)", max_length=100, blank=True
    )
    film_embed_code = models.TextField(
        "Film HTML kodi (Eski)", blank=True, default="<div>...</div>"
    )
    trailer_embed_code = models.TextField("Trailer HTML kodi (Eski)", blank=True)
    site_rank = models.IntegerField("Sayt reytingi (Ichki)", default=0)
    mdl_rank = models.DecimalField(
        "MyDramaList Reytingi", max_digits=4, decimal_places=1, default=0.0
    )
    main_actors = models.ManyToManyField(Actor, related_name="main_acted_movies")
    actors = models.ManyToManyField(Actor, related_name="acted_movies")
    genres = models.ManyToManyField(Genre)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, related_name="movies"
    )
    slug = models.SlugField(max_length=160, unique=True)
    is_draft = models.BooleanField("Qoralama (Draft)", default=False)
    # Denormalization (Tezlik uchun)
    total_votes = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["year"]),
            models.Index(fields=["created_at"]),
            # FIX: is_draft ko'p joylarda filter shart — indeks qo'shildi
            models.Index(fields=["is_draft"]),
            models.Index(fields=["is_draft", "-created_at"]),
        ]
        verbose_name = "Kino"
        verbose_name_plural = "Kinolar"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        # FIX: try/except qo'shildi — concurrent o'chirish (race condition) dan himoya
        if self.pk:
            try:
                old_poster = Movie.objects.get(pk=self.pk).poster
                if old_poster != self.poster:
                    self.poster = optimize_image(self.poster, self.slug)
            except Movie.DoesNotExist:
                self.poster = optimize_image(self.poster, self.slug)
        else:
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
    bunny_video_id = models.CharField("Bunny Stream Video ID", max_length=100, blank=True)
    video_embed_code = models.TextField("Video HTML kodi (Eski / Embed)", blank=True)
    thumbnail = models.ImageField("Qism uchun rasm", upload_to="episodes/", blank=True, null=True)

    class Meta:
        # FIX: Bir serialda bir xil qism raqami bo'lishini oldini olish
        unique_together = ("movie", "episode_number")
        ordering = ["episode_number"]
        verbose_name = "Qism"
        verbose_name_plural = "Qismlar"

    def save(self, *args, **kwargs):
        if self.thumbnail and hasattr(self.thumbnail, "file"):
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
        if self.image and hasattr(self.image, "file"):
            name_base = f"{self.movie.title}-shot-{self.id or 'new'}"
            self.image = optimize_image(self.image, name_base)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


# --- Reyting va Izoh Modellarida o'zgarish yo'q ---
class RatingStar(models.Model):
    value = models.PositiveSmallIntegerField("Qiymat", default=0)

    def __str__(self):
        return str(self.value)


class Rating(models.Model):
    ip = models.GenericIPAddressField("IP Manzil")
    star = models.ForeignKey(RatingStar, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="ratings")


class Review(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="reviews")
    text = models.TextField("Izoh matni", max_length=5000)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="replies"
    )


class ActorGift(models.Model):
    GIFT_CHOICES = (
        ("rose", "Gul 🌹"),
        ("coffee", "Qahva ☕"),
        ("crown", "Toj 👑"),
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_gifts", verbose_name="Foydalanuvchi"
    )
    actor = models.ForeignKey(
        Actor, on_delete=models.CASCADE, related_name="received_gifts", verbose_name="Aktyor"
    )
    gift_type = models.CharField("Sovg'a turi", max_length=20, choices=GIFT_CHOICES)
    price = models.PositiveIntegerField("Narxi (Coin)")
    created_at = models.DateTimeField("Yuborilgan vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "Aktyorga Sovg'a"
        verbose_name_plural = "Aktyorlarga Sovg'alar"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} -> {self.actor.name} ({self.get_gift_type_display()})"
