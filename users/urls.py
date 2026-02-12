# users/urls.py
from django.urls import path
from . import views as user_views
from django.contrib.auth import views as auth_views

app_name = 'users' # MUHIM: Namespace shu yerda belgilanadi

urlpatterns = [
    path('register/', user_views.register, name='register'),
    path('profile/<str:username>/', user_views.profile_view, name='profile'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
    path('dramalist/', user_views.my_full_list, name='my_full_list'),
    path('settings/', user_views.settings_view, name='settings'),
]