from django.urls import path

from . import views

app_name = "funding"

urlpatterns = [
    path("process/<int:project_id>/", views.process_funding, name="process"),
]
