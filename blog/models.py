"""Blog / Yangiliklar modellari [V2G-T2].

Yengil kontent-marketing blogi: K-drama yangiliklari va sharhlari. Movie'ning
publish-workflow naqshini (draft/scheduled/published + publish_at) aynan
takrorlaydi, shu bois `published()` invarianti butun saytda bir xil ishlaydi.

Kontent bilingual (modeltranslation, blog/translation.py) — bo'sh en uz'ga
qaytadi (movies bilan bir xil fallback). `slug` ATAYLAB tarjima qilinmaydi:
URL til-neytral bo'lishi kerak (/yangiliklar/<slug>/ va /en/yangiliklar/<slug>/
bir xil), aks holda V2G-T1 hreflang juftligi buzilardi.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.images import ImageOptimizationMixin
from drama.models import Movie, Tag, TimeStampedModel


class PostQuerySet(models.QuerySet):
    """Movie bilan bir xil ko'rinish-invarianti [V2G-T2]."""

    def published(self) -> PostQuerySet:
        """Ommaviy: status=published YOKI (scheduled VA publish_at o'tgan)."""
        return self.filter(
            models.Q(status=Post.Status.PUBLISHED)
            | models.Q(status=Post.Status.SCHEDULED, publish_at__lte=timezone.now())
        )

    def drafts(self) -> PostQuerySet:
        return self.filter(status=Post.Status.DRAFT)

    def with_related(self) -> PostQuerySet:
        """Detal/lenta uchun N+1'siz (author + tags)."""
        return self.select_related("author").prefetch_related("tags")


class Post(ImageOptimizationMixin, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        SCHEDULED = "scheduled", "Rejalashtirilgan"
        PUBLISHED = "published", "Chop etilgan"

    title = models.CharField("Sarlavha", max_length=200)
    slug = models.SlugField("Slug", max_length=220, unique=True, db_index=True)
    excerpt = models.CharField(
        "Qisqa tavsif",
        max_length=300,
        blank=True,
        help_text="Lenta/kartada va meta-description'da ishlatiladi. Bo'sh bo'lsa "
        "matn boshidan avtomatik olinadi.",
    )
    body = models.TextField("Matn (HTML)", help_text="Rich-text — admin muharriri.")
    cover = models.ImageField("Muqova rasmi", upload_to="blog/covers/", blank=True)

    status = models.CharField("Holat", max_length=12, choices=Status.choices, default=Status.DRAFT)
    publish_at = models.DateTimeField(
        "Chop etish vaqti",
        null=True,
        blank=True,
        help_text="Rejalashtirilgan holat uchun majburiy — shu vaqtdan keyin ommaviy bo'ladi.",
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
        verbose_name="Muallif",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts", verbose_name="Teglar")
    related_movies = models.ManyToManyField(
        Movie,
        blank=True,
        related_name="blog_posts",
        verbose_name="Bog'liq kinolar",
        help_text="Ichki havolalar (SEO link-building) — maqola oxirida ko'rsatiladi.",
    )

    # Cover Celery'da optimallashadi (movie poster kabi)
    OPTIMIZE_IMAGE_FIELDS = {"cover": {"max_size": (1600, 900), "quality": 82}}

    objects = PostQuerySet.as_manager()

    class Meta:
        verbose_name = "Maqola"
        verbose_name_plural = "Maqolalar"
        ordering = ["-publish_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "publish_at"]),
            models.Index(fields=["slug"]),
        ]
        constraints = [
            # scheduled bo'lsa publish_at majburiy (aks holda hech qachon chop etilmaydi)
            models.CheckConstraint(
                condition=~models.Q(status="scheduled") | models.Q(publish_at__isnull=False),
                name="post_scheduled_requires_publish_at",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.status == self.Status.SCHEDULED and not self.publish_at:
            raise ValidationError(
                {"publish_at": "Rejalashtirilgan maqola uchun chop etish vaqti majburiy."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            base = slugify(self.title) or "maqola"
            slug = base
            i = 2
            # Noyoblikni ta'minlaymiz (kirill sarlavha -> bo'sh slugify bo'lishi mumkin)
            while Post.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        # published bo'lsa va publish_at bo'sh bo'lsa — hozirni qo'yamiz (lenta tartibi uchun)
        if self.status == self.Status.PUBLISHED and not self.publish_at:
            self.publish_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("blog:post_detail", kwargs={"slug": self.slug})

    @property
    def is_public(self) -> bool:
        """Ayni damda ommaviy ko'rinadimi (detail 404 qarori uchun)."""
        if self.status == self.Status.PUBLISHED:
            return True
        return self.status == self.Status.SCHEDULED and bool(
            self.publish_at and self.publish_at <= timezone.now()
        )

    @property
    def summary(self) -> str:
        """excerpt yoki matndan avtomatik (meta-description/lenta uchun)."""
        if self.excerpt:
            return self.excerpt
        from django.utils.html import strip_tags

        text = strip_tags(self.body).strip()
        return (text[:157] + "…") if len(text) > 160 else text
