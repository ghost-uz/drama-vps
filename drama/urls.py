from django.urls import path

from . import views

app_name = "drama"

urlpatterns = [
    path("", views.MoviesView.as_view(), name="movie_list"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    # Qidiruv va Filtr
    path("explore/", views.FilterMoviesView.as_view(), name="explore"),
    path("search/", views.Search.as_view(), name="search"),
    path("live-search/", views.live_search, name="live_search"),
    path("tag/<slug:slug>/", views.TagDetailView.as_view(), name="tag_detail"),
    # Detallar
    path("janr/<slug:slug>/", views.GenreDetailView.as_view(), name="genre_detail"),
    path("inson/<slug:slug>/", views.ActorView.as_view(), name="actor_detail"),
    # Funksiyalar
    path("review/<int:pk>/", views.AddReview.as_view(), name="add_review"),
    path("review/<int:pk>/report/", views.report_review, name="report_review"),
    path("add-to-list/<int:movie_id>/", views.add_to_list, name="add_to_list"),
    path("actor/<int:actor_id>/gift/", views.send_gift_to_actor, name="send_gift_to_actor"),
    path(
        "episode/<int:episode_id>/progress/",
        views.save_watch_progress,
        name="save_watch_progress",
    ),
    # =========================================================
    # 🌟 YANGI QO'SHILGAN QISM: Barcha fikrlar uchun sahifa
    path("<slug:slug>/reviews/", views.MovieReviewsView.as_view(), name="movie_reviews"),
    # =========================================================
    # Kino slug (Eng pastda bo'lishi shart!)
    path("<slug:slug>/", views.MovieDetailView.as_view(), name="movie_detail"),
]
