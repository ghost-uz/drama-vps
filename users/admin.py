from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from unfold.admin import ModelAdmin, StackedInline
# MANA SHU QATORNI QO'SHING:
from unfold.decorators import display 
from .models import Profile

class ProfileInline(StackedInline): 
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profil Ma\'lumotlari'
    fields = ('is_premium', 'premium_until', 'avatar', 'bio', 'telegram_id')

admin.site.unregister(User)

@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'get_is_premium', 'is_staff')

    @display(description="VIP Status", boolean=True)
    def get_is_premium(self, instance):
        try:
            # users/models.py dagi property-ni chaqiramiz
            return instance.profile.is_currently_premium
        except (AttributeError, Profile.DoesNotExist):
            return False