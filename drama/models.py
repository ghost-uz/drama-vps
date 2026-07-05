from datetime import date

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.images import ImageOptimizationMixin, is_new_upload
from core.validators import ImageFileValidator, VideoFileValidator


def movie_poster_path(instance, filename):
    """Eski migratsiyalar uchun saqlab qolindi.

    Yangi fayllar ImageOptimizationMixin (Celery fon-siqish) orqali boshqariladi.
    """
    ext = filename.split(".")[-1]
    name = slugify(instance.title if hasattr(instance, "title") else "poster")
    return f"movies/{name}.{ext}"


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


class Actor(ImageOptimizationMixin, models.Model):
    OPTIMIZE_IMAGE_FIELDS = {"image": {"max_size": (1280, 1280), "quality": 80}}

    GENDER_CHOICES = (("male", "Erkak"), ("female", "Ayol"))
    name = models.CharField("Ism Familiya", max_length=150)
    original_name = models.CharField("Asl ismi (Native)", max_length=150, blank=True)
    description = models.TextField("Biografiya", blank=True)
    image = models.ImageField("Rasmi", upload_to="actors/", validators=[ImageFileValidator()])
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
        if not self.slug:
            self.slug = slugify(self.name)
        # Rasm siqish ImageOptimizationMixin.save() orqali fon (Celery)da.
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("drama:actor_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.name


class TopSlider(ImageOptimizationMixin, models.Model):
    OPTIMIZE_IMAGE_FIELDS = {"image": {"max_size": (1280, 1280), "quality": 80}}

    name = models.CharField("Slayder nomi", max_length=100, null=True)
    rank = models.CharField("Rank matni", max_length=50)
    image = models.ImageField(
        "Slayder rasmi", upload_to="sliders/", validators=[ImageFileValidator()]
    )
    target_url = models.URLField("Yo'naltiriluvchi URL", blank=True)

    def __str__(self):
        return self.name or "Slayder"


# --- Asosiy Film Modeli ---


class UploadStatus(models.TextChoices):
    """video_file -> Bunny pipeline holatlari (Movie va Episode umumiy) [P14-T1]."""

    NONE = "none", "Yo'q"
    UPLOADING = "uploading", "Yuklanmoqda"
    PROCESSING = "processing", "Qayta ishlanmoqda (encoding)"
    READY = "ready", "Tayyor"
    FAILED = "failed", "Xato"


class MovieQuerySet(models.QuerySet):
    """Movie ko'rinish invariantlarini bitta joyga jamlaydi (DRY + xavfsizlik).

    Har bir view'da `filter(status=...)` ni qo'lda takrorlash o'rniga
    `Movie.objects.published()` ishlatiladi — bittasini unutsa qoralama sizib
    chiqishi xavfi yo'qoladi.
    """

    def published(self):
        """Public saytda ko'rinadigan kinolar.

        status=published YOKI (status=scheduled VA publish_at o'tib ketgan).
        Ikkinchi shart — self-healing: Celery beat o'lib qolsa ham, vaqti
        yetgan rejalashtirilgan kino public bo'lib ko'rinaveradi.
        """
        return self.filter(
            models.Q(status=Movie.Status.PUBLISHED)
            | models.Q(status=Movie.Status.SCHEDULED, publish_at__lte=timezone.now())
        )

    def drafts(self):
        return self.filter(status=Movie.Status.DRAFT)

    def due_for_publish(self):
        """Beat task uchun: vaqti yetgan, hali 'scheduled' turgan kinolar."""
        return self.filter(status=Movie.Status.SCHEDULED, publish_at__lte=timezone.now())

    def with_card_data(self):
        """Karta (movies_card.html) uchun qismlar soni — N+1'siz [P9-T2].

        Shablondagi `movie.episodes.count` har karta uchun 3 ta COUNT so'rovi
        edi; annotation bitta LEFT JOIN bilan keladi. distinct=True — filtr
        JOIN'lari (masalan, bir nechta janr) qatorlarni ko'paytirganda ham son
        to'g'ri qoladi.
        """
        return self.annotate(live_episode_count=models.Count("episodes", distinct=True))


class Movie(ImageOptimizationMixin, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        SCHEDULED = "scheduled", "Rejalashtirilgan"
        PUBLISHED = "published", "Chop etilgan"

    OPTIMIZE_IMAGE_FIELDS = {
        "poster": {
            "max_size": (1280, 1280),
            "quality": 80,
            # Karta varianti (srcset uchun) — task asosiy webp'dan keyin yaratadi [P5-T5]
            "card": {"field": "poster_card", "max_size": (342, 513), "quality": 78},
        }
    }

    objects = MovieQuerySet.as_manager()

    title = models.CharField("Film nomi (Qidiruv uchun)", max_length=255, db_index=True)
    original_title = models.CharField("Original nomi (Kdrama)", max_length=255, blank=True)
    is_vip = models.BooleanField(default=False)
    tagline = models.CharField("Slogan", max_length=255, blank=True)
    description = models.TextField("Tavsif")
    poster = models.ImageField("Rasmi", upload_to="movies/", validators=[ImageFileValidator()])
    # Karta o'lchami (srcset) — optimize_image_task avtomatik to'ldiradi [P5-T5]
    poster_card = models.ImageField(
        "Poster (karta, 342px)", upload_to="movies/cards/", blank=True, null=True, editable=False
    )
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
    # Yakka film videosi: fayl yuklansa Bunny pipeline avto-ishlaydi [P14-T1]
    video_file = models.FileField(
        "Video fayl (Bunny'ga avtomatik yuklanadi)",
        upload_to="movie_uploads/",
        blank=True,
        null=True,
        validators=[VideoFileValidator(max_mb=500)],
    )
    upload_status = models.CharField(
        "Yuklash holati", max_length=12, choices=UploadStatus, default=UploadStatus.NONE
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
    status = models.CharField(
        "Holat",
        max_length=10,
        choices=Status.choices,
        default=Status.PUBLISHED,
    )
    publish_at = models.DateTimeField(
        "Chop etish vaqti",
        null=True,
        blank=True,
        help_text="'Rejalashtirilgan' bo'lsa: shu vaqtda avtomatik chop etiladi.",
    )
    # Denormalization (Tezlik uchun)
    total_votes = models.PositiveIntegerField(default=0)
    # max_digits=4 (3 emas): 10.00 baho saqlanishi uchun (3 → maksimum 9.99 edi — bug).
    average_rating = models.DecimalField(max_digits=4, decimal_places=2, default=0.0)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["year"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["status", "publish_at"]),
            # Explore filtri va davlatlar ro'yxati (distinct) uchun [P9-T2]
            models.Index(fields=["country"]),
        ]
        constraints = [
            # scheduled bo'lsa publish_at majburiy (aks holda hech qachon chop etilmaydi)
            models.CheckConstraint(
                condition=~models.Q(status="scheduled") | models.Q(publish_at__isnull=False),
                name="movie_scheduled_requires_publish_at",
            ),
        ]
        verbose_name = "Kino"
        verbose_name_plural = "Kinolar"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.status == self.Status.SCHEDULED and not self.publish_at:
            raise ValidationError(
                {"publish_at": "Rejalashtirilgan kino uchun chop etish vaqti majburiy."}
            )

    def save(self, *args, **kwargs):
        from functools import partial

        from django.db import transaction

        if not self.slug:
            self.slug = slugify(self.title)
        # Yakka film videosi: yangi fayl -> Bunny pipeline (Episode bilan bir xil yo'l)
        new_video = is_new_upload(self.video_file)
        if new_video:
            self.upload_status = UploadStatus.UPLOADING
        # Poster siqish ImageOptimizationMixin.save() orqali fon (Celery)da.
        super().save(*args, **kwargs)
        if new_video:
            from drama.tasks import process_video_upload

            transaction.on_commit(partial(process_video_upload.delay, "drama", "movie", self.pk))

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("drama:movie_detail", kwargs={"slug": self.slug})


class Season(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="seasons")
    number = models.PositiveIntegerField("Fasl raqami", default=1)
    title = models.CharField("Fasl nomi", max_length=150, blank=True)
    year = models.PositiveSmallIntegerField("Yili", null=True, blank=True)

    class Meta:
        unique_together = ("movie", "number")
        ordering = ["number"]
        verbose_name = "Fasl"
        verbose_name_plural = "Fasllar"

    def __str__(self):
        return self.title or f"{self.movie.title} - {self.number}-fasl"


class Episode(ImageOptimizationMixin, TimeStampedModel):
    OPTIMIZE_IMAGE_FIELDS = {"thumbnail": {"max_size": (1280, 1280), "quality": 80}}

    # Modul-darajali umumiy holatlar (Movie bilan bitta) — eski `Episode.UploadStatus`
    # murojaatlari (tasks/webhooks/testlar) alias orqali ishlayveradi [P14-T1]
    UploadStatus = UploadStatus

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="episodes")
    # Backward-compat: movie SAQLANADI (eski view/admin movie.episodes ishlatadi).
    # season null=True — data migration (0018) mavjud episodelarni "Season 1"ga bog'laydi.
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="episodes", null=True, blank=True
    )
    title = models.CharField("Qism nomi", max_length=150)
    episode_number = models.PositiveIntegerField("Qism raqami")
    bunny_video_id = models.CharField("Bunny Stream Video ID", max_length=100, blank=True)
    video_file = models.FileField(
        "Video fayl (Bunny'ga avtomatik yuklanadi)",
        upload_to="episode_uploads/",
        blank=True,
        null=True,
        validators=[VideoFileValidator(max_mb=500)],
    )
    upload_status = models.CharField(
        "Yuklash holati", max_length=12, choices=UploadStatus, default=UploadStatus.NONE
    )
    video_embed_code = models.TextField("Video HTML kodi (Eski / Embed)", blank=True)
    thumbnail = models.ImageField(
        "Qism uchun rasm",
        upload_to="episodes/",
        blank=True,
        null=True,
        validators=[ImageFileValidator()],
    )

    class Meta:
        # FIX: Bir serialda bir xil qism raqami bo'lishini oldini olish
        unique_together = ("movie", "episode_number")
        ordering = ["episode_number"]
        verbose_name = "Qism"
        verbose_name_plural = "Qismlar"

    def save(self, *args, **kwargs):
        from functools import partial

        from django.db import transaction

        new_video = is_new_upload(self.video_file)
        if new_video:
            self.upload_status = self.UploadStatus.UPLOADING
        # super().save() ImageOptimizationMixin orqali thumbnail'ni fon (Celery)da siqadi
        super().save(*args, **kwargs)
        if new_video:
            from drama.tasks import process_video_upload

            transaction.on_commit(partial(process_video_upload.delay, "drama", "episode", self.pk))

    def __str__(self):
        return f"{self.movie.title} - {self.episode_number}-qism"


class MovieShots(ImageOptimizationMixin, models.Model):
    OPTIMIZE_IMAGE_FIELDS = {"image": {"max_size": (1280, 1280), "quality": 80}}

    title = models.CharField("Sarlavha", max_length=100)
    description = models.TextField("Tavsif", blank=True)
    image = models.ImageField("Rasm", upload_to="movie_shots/", validators=[ImageFileValidator()])
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="shots")

    def __str__(self):
        return self.title


# --- Reyting va Izoh Modellari ---
class RatingStar(models.Model):
    """DEPRECATED (P1-T5): eski IP-reyting yulduzi. Yangi manba — UserMovieList.score.

    Faqat tarixiy/arxiv ma'lumot uchun saqlanadi (yangi kod ishlatmaydi).
    """

    value = models.PositiveSmallIntegerField("Qiymat", default=0)

    def __str__(self):
        return str(self.value)


class Rating(models.Model):
    """DEPRECATED (P1-T5): IP-asosli anonim reyting (foydalanuvchiga bog'lanmagan).

    Yagona yangi manba — UserMovieList.score (recompute_movie_rating task).
    Bu model arxiv sifatida saqlanadi; yangi yozuv yaratilmaydi.
    """

    ip = models.GenericIPAddressField("IP Manzil")
    star = models.ForeignKey(RatingStar, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="ratings")


class Review(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="reviews")
    text = models.TextField("Izoh matni", max_length=5000)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="replies"
    )

    class Meta:
        # Detail/fikrlar sahifasi: filter(movie=..., parent=None) [P9-T2]
        indexes = [models.Index(fields=["movie", "parent"])]


class ActorGift(models.Model):
    GIFT_CHOICES = (
        ("rose", "Gul 🌹"),
        ("coffee", "Qahva ☕"),
        ("crown", "Toj 👑"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_gifts",
        verbose_name="Foydalanuvchi",
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
