# users/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views as user_views
from .views import followers_view, following_view

app_name = "users"

urlpatterns = [
    path("register/", user_views.register, name="register"),
    path("profile/<str:username>/", user_views.profile_view, name="profile"),
    # Follow / Unfollow (POST-only, CSRF himoyasi bilan)
    path("follow/<str:username>/", user_views.follow_user, name="follow"),
    path("unfollow/<str:username>/", user_views.unfollow_user, name="unfollow"),
    # Follower / Following ro'yxatlari
    path("user/<str:username>/followers/", followers_view, name="followers"),
    path("user/<str:username>/following/", following_view, name="following"),
    # Auth
    path("login/", auth_views.LoginView.as_view(template_name="users/login.html"), name="login"),
    path(
        "logout/", auth_views.LogoutView.as_view(template_name="users/logout.html"), name="logout"
    ),
    # Kino ro'yxati
    path("dramalist/<str:username>/", user_views.user_full_list, name="user_drama_list"),
    # Hisob
    path("settings/", user_views.settings_view, name="settings"),
    path("topup/", user_views.topup_view, name="topup"),
    path("topup/crypto/", user_views.crypto_topup_view, name="crypto_topup"),
    path("subscription/", user_views.subscription_view, name="subscription"),
    path("buy-vip/", user_views.buy_premium, name="buy_premium"),
    path("transactions/", user_views.transactions_view, name="transactions"),
]
