# users/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django_ratelimit.decorators import ratelimit

from core.ratelimit import ip_key, rate

from . import views as user_views
from .forms import AsyncPasswordResetForm
from .views import followers_view, following_view

app_name = "users"

urlpatterns = [
    path("register/", user_views.register, name="register"),
    # Email tasdiqlash [P6-T1]
    path("verify-email/<str:key>/", user_views.verify_email, name="verify_email"),
    path("resend-verification/", user_views.resend_verification, name="resend_verification"),
    path("profile/<str:username>/", user_views.profile_view, name="profile"),
    # Follow / Unfollow (POST-only, CSRF himoyasi bilan)
    path("follow/<str:username>/", user_views.follow_user, name="follow"),
    path("unfollow/<str:username>/", user_views.unfollow_user, name="unfollow"),
    # Follower / Following ro'yxatlari
    path("user/<str:username>/followers/", followers_view, name="followers"),
    path("user/<str:username>/following/", following_view, name="following"),
    # Auth
    # Login brute-force himoyasi: POST 10/daqiqa/IP [P10-T2]
    path(
        "login/",
        ratelimit(key=ip_key, rate=rate, group="login", method="POST", block=True)(
            auth_views.LoginView.as_view(template_name="users/login.html")
        ),
        name="login",
    ),
    path(
        "logout/", auth_views.LogoutView.as_view(template_name="users/logout.html"), name="logout"
    ),
    # Telegram orqali kirish (Login Widget GET + Mini App POST) [P6-T2]
    path("telegram/login/", user_views.telegram_login, name="telegram_login"),
    # Parol tiklash [P6-T1] — Django built-in view'lar, email fon (Celery)da ketadi.
    # DIQQAT: default template/success_url'lar namespace'SIZ nom reverse qiladi —
    # shu sabab success_url va email shablonlari aniq ko'rsatilgan.
    path(
        "password-reset/",
        ratelimit(key=ip_key, rate=rate, group="password_reset", method="POST", block=True)(
            auth_views.PasswordResetView.as_view(
                template_name="users/password_reset.html",
                form_class=AsyncPasswordResetForm,
                email_template_name="users/password_reset_email.txt",
                subject_template_name="users/password_reset_subject.txt",
                success_url=reverse_lazy("users:password_reset_done"),
            )
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="users/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="users/password_reset_confirm.html",
            success_url=reverse_lazy("users:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="users/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Kino ro'yxati
    path("dramalist/<str:username>/", user_views.user_full_list, name="user_drama_list"),
    # --- Kolleksiyalar [V2B-T4] ---
    path("kolleksiyalar/", user_views.my_collections, name="my_collections"),
    path("kolleksiyalar/<slug:slug>/tahrir/", user_views.collection_edit, name="collection_edit"),
    path(
        "kolleksiyalar/<slug:slug>/delete/", user_views.collection_delete, name="collection_delete"
    ),
    path("kolleksiyalar/<slug:slug>/add/", user_views.collection_add, name="collection_add"),
    path(
        "kolleksiyalar/<slug:slug>/search/", user_views.collection_search, name="collection_search"
    ),
    path(
        "kolleksiyalar/<slug:slug>/item/<int:item_id>/remove/",
        user_views.collection_item_remove,
        name="collection_item_remove",
    ),
    path(
        "kolleksiyalar/<slug:slug>/item/<int:item_id>/move/",
        user_views.collection_item_move,
        name="collection_item_move",
    ),
    # Ommaviy URL: /users/<u>/collections/<slug>/ (OG preview bilan)
    path(
        "<str:username>/collections/<slug:slug>/",
        user_views.collection_detail,
        name="collection_detail",
    ),
    # Hisob
    path("settings/", user_views.settings_view, name="settings"),
    # Telegram bot ulash/uzish [V2A-T2]
    path("settings/telegram-bot/link/", user_views.telegram_bot_link, name="telegram_bot_link"),
    path(
        "settings/telegram-bot/unlink/",
        user_views.telegram_bot_unlink,
        name="telegram_bot_unlink",
    ),
    path("topup/", user_views.topup_view, name="topup"),
    path("topup/crypto/", user_views.crypto_topup_view, name="crypto_topup"),
    path("subscription/", user_views.subscription_view, name="subscription"),
    path("subscription/auto-renew/", user_views.toggle_auto_renew, name="toggle_auto_renew"),
    path("buy-vip/", user_views.buy_premium, name="buy_premium"),
    path("transactions/", user_views.transactions_view, name="transactions"),
    # Bildirishnomalar markazi [P6-T3]
    path("bildirishnomalar/", user_views.notifications_view, name="notifications"),
    path(
        "bildirishnomalar/<int:pk>/read/",
        user_views.mark_notification_read,
        name="notification_read",
    ),
    path(
        "bildirishnomalar/read-all/",
        user_views.mark_all_notifications_read,
        name="notifications_read_all",
    ),
]
