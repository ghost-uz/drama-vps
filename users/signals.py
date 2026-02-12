from django.db.models.signals import post_save, pre_save, post_delete
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile
import logging

# Xatolarni log qilish uchun (ixtiyoriy)
logger = logging.getLogger(__name__)

# 1 va 2 ni birlashtiramiz: User yaratilganda Profil yaratish va saqlash
@receiver(post_save, sender=User)
def manage_user_profile(sender, instance, created, **kwargs):
    if created:
        # User yaratilganda profilni get_or_create bilan ochish xavfsizroq
        Profile.objects.get_or_create(user=instance)
    # else qismidagi save() ni o'chiramiz, chunki User.save() 
    # chaqirilganda Profile.save() ni chaqirish shart emas (OneToOneCASCADE)

# Qolgan pre_save va post_delete kodlaringiz o'zgarishsiz qolishi mumkin...
# 3. Rasm yangilanganda eski rasmni o'chirish (Xavfsizroq ko'rinishda)
@receiver(pre_save, sender=Profile)
def delete_old_avatar_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_profile = Profile.objects.get(pk=instance.pk)
        old_avatar = old_profile.avatar
    except Profile.DoesNotExist:
        return False

    new_avatar = instance.avatar
    
    # Agar rasm o'zgargan bo'lsa va eski rasm mavjud bo'lsa
    if old_avatar and old_avatar != new_avatar:
        # Rasm default rasm emasligini tekshirish (agar static ichida bo'lsa)
        if 'default.jpg' not in old_avatar.name: 
            try:
                old_avatar.delete(save=False)
            except Exception as e:
                logger.error(f"Eski rasmni o'chirishda xatolik: {e}")

# 4. Profil o'chirilganda rasmni o'chirish
@receiver(post_delete, sender=Profile)
def delete_avatar_on_profile_delete(sender, instance, **kwargs):
    # GCS bilan ishlashda juda ehtiyot bo'lish kerak
    if instance.avatar and 'default.jpg' not in instance.avatar.name:
        try:
            # storage.delete ishlatish xavfsizroq
            storage = instance.avatar.storage
            if storage.exists(instance.avatar.name):
                storage.delete(instance.avatar.name)
        except Exception as e:
            logger.error(f"Rasmni o'chirishda xatolik yuz berdi: {e}")