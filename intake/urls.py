from django.urls import path

from . import views

app_name = "intake"

urlpatterns = [
    path("", views.NoteListView.as_view(), name="list"),
    path("quick-add/", views.quick_add, name="quick-add"),
    path("<int:pk>/edit/", views.NoteUpdateView.as_view(), name="update"),
    path("<int:pk>/archive/", views.toggle_archive, name="toggle-archive"),
    path("<int:pk>/create-client/", views.CreateClientFromNoteView.as_view(), name="create-client"),
]

