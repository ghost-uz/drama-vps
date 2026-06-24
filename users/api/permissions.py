"""users/api/permissions.py — umumiy API ruxsatlari [P2-T3]."""

from rest_framework import permissions


class IsOwnerOrAdmin(permissions.BasePermission):
    """Xavfsiz metodlar hammaga; o'zgartirish/o'chirish faqat egasi yoki staff.

    Obyektning egasini `user` atributidan oladi (Review, WatchProgress).
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "user", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user == owner or request.user.is_staff)
        )
