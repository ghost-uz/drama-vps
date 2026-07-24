from django.urls import path

from . import views
from .feeds import LatestPostsFeed

app_name = "blog"

urlpatterns = [
    path("", views.PostListView.as_view(), name="post_list"),
    # RSS — slug catch-all'dan OLDIN (aks holda "rss" slug deb qabul qilinardi)
    path("rss/", LatestPostsFeed(), name="rss"),
    # Slug catch-all — eng pastda
    path("<slug:slug>/", views.PostDetailView.as_view(), name="post_detail"),
]
