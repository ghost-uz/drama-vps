# users/utils.py
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404

def get_user_by_username(username):
    return get_object_or_404(User, username=username)

def follow(from_user, to_user):
    """from_user → to_user ni follow qiladi"""
    # ✅ Profile orqali bog'laymiz
    from_user.profile.following.add(to_user.profile)

def unfollow(from_user, to_user):
    """from_user → to_user ni unfollow qiladi"""
    from_user.profile.following.remove(to_user.profile)