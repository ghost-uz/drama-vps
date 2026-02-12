from django.urls import path
from . import views

app_name = 'drama'

urlpatterns = [
    path("", views.MoviesView.as_view(), name="movie_list"),
    path("robots.txt/", views.robots_txt, name="robots_txt"),
    
    # Qidiruv va Filtr
    path("explore/", views.FilterMoviesView.as_view(), name="explore"),
    path("search/", views.Search.as_view(), name="search"),
    path("live-search/", views.live_search, name="live_search"),
    
    # Detallar
    path("janr/<slug:slug>/", views.GenreDetailView.as_view(), name="genre_detail"),
    path("inson/<slug:slug>/", views.ActorView.as_view(), name="actor_detail"),
    
    # Funksiyalar
    path("review/<int:pk>/", views.AddReview.as_view(), name="add_review"),
    path("add-to-list/<int:movie_id>/", views.add_to_list, name="add_to_list"),
    
    # Kino slug (Eng pastda)
    path("<slug:slug>/", views.MovieDetailView.as_view(), name="movie_detail"),
]