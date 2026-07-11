"""core/models.py — umumiy modellar. Birinchi model: AuditLog [P10-T4]."""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Muhim amallar auditi — kim, nima, qachon (o'zgarmas yozuv).

    Django'ning admin LogEntry'si faqat admin FORMA saqlashlarini qamraydi;
    bu jadval biznes-amallar (topup tasdiq, publish, moderatsiya, funding
    bekor qilish) uchun. Yozishning yagona nuqtasi — core/audit.py :: log().
    Admin'da faqat o'qiladi (core/admin.py permissionlari yopiq).
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name="Bajaruvchi",
    )
    action = models.CharField("Amal", max_length=60)
    target = models.CharField("Obyekt", max_length=200, blank=True)
    details = models.CharField("Tafsilot", max_length=500, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["action", "-created_at"])]
        verbose_name = "Audit yozuvi"
        verbose_name_plural = "Audit jurnali"

    def __str__(self):
        who = self.actor.username if self.actor else "tizim"
        return f"{who}: {self.action} {self.target}".strip()
