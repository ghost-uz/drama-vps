# users/urls.py
from django.urls import path
from .views import profile_detail
from . import views as user_views
from django.contrib.auth import views as auth_views
from users.utils import get_user_by_username, follow, unfollow
from .views import followers_view, following_view

app_name = 'users' # MUHIM: Namespace shu yerda belgilanadi

urlpatterns = [
    path('register/', user_views.register, name='register'),
    path('profile/<str:username>/', user_views.profile_view, name='profile'),
    # ✅ follow_user → follow, unfollow_user → unfollow
    path('follow/<str:username>/', user_views.follow_user, name='follow'),
    path('unfollow/<str:username>/', user_views.unfollow_user, name='unfollow'),
    # ... kutilgan URL lar ...
    path('user/<username>/followers/', user_views.followers_view, name='followers'),
    path('user/<username>/following/', user_views.following_view, name='following'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
    path('dramalist/<str:username>/', user_views.user_full_list, name='user_drama_list'),
    path('settings/', user_views.settings_view, name='settings'),
    path('topup/', user_views.topup_view, name='topup'),
    path('subscription/', user_views.subscription_view, name='subscription'),
    path('buy-vip/', user_views.buy_premium, name='buy_premium'),
]