import logging
from functools import partial

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Profile, UserMovieList

logger = logging.getLogger(__name__)


# 1. PROFILE YARATISH (O'chirmang, bu juda muhim!)
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Yangi user ro'yxatdan o'tganda profil yaratadi"""
    if created:
        Profile.objects.get_or_create(user=instance)


# 2. ESKI RASMNI O'CHIRISH (Men bergan qism)
@receiver(pre_save, sender=Profile)
def delete_old_avatar_on_change(sender, instance, **kwargs):
    """Rasm o'zgarganda bulutdagi eskisini o'chiradi"""
    if not instance.pk:
        return  # Yangi profil bo'lsa to'xtatish

    try:
        old_obj = Profile.objects.get(pk=instance.pk)
    except Profile.DoesNotExist:
        return

    # Agar rasm maydoni o'zgargan bo'lsa va u default bo'lmasa
    if old_obj.avatar and old_obj.avatar != instance.avatar:
        if "default.jpg" not in old_obj.avatar.name:
            try:
                storage = old_obj.avatar.storage
                if storage.exists(old_obj.avatar.name):
                    storage.delete(old_obj.avatar.name)
            except Exception as e:
                logger.error(f"Eski rasmni o'chirishda xato: {e}")


# 3. PROFIL O'CHIRILGANDA TOZALASH
@receiver(post_delete, sender=Profile)
def delete_avatar_on_profile_delete(sender, instance, **kwargs):
    """Profil o'chsa, rasm ham bulutdan yo'qoladi"""
    if instance.avatar and "default.jpg" not in instance.avatar.name:
        try:
            storage = instance.avatar.storage
            if storage.exists(instance.avatar.name):
                storage.delete(instance.avatar.name)
        except Exception as e:
            logger.error(f"Profil o'chganda rasm o'chmadi: {e}")


# 4. REYTINGNI QAYTA HISOBLASH (P1-T5)
@receiver(post_save, sender=UserMovieList)
@receiver(post_delete, sender=UserMovieList)
def recompute_rating_on_score_change(sender, instance, **kwargs):
    """Baho (UserMovieList.score) o'zgarganda Movie reytingini fon'da qayta hisoblaydi.

    on_commit: worker commit qilingan ma'lumotni o'qiydi; .delay(): request bloklanmaydi.
    """
    from drama.tasks import recompute_movie_rating

    movie_id = instance.movie_id
    transaction.on_commit(partial(recompute_movie_rating.delay, movie_id))
