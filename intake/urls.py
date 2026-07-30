from django.urls import path

from . import views

app_name = "intake"

urlpatterns = [
    path("", views.NoteListView.as_view(), name="list"),
    path("quick-add/", views.quick_add, name="quick-add"),
    path("project-options/", views.project_options, name="project-options"),
    path("new/", views.NoteCreateView.as_view(), name="create"),
    path("<int:pk>/", views.NoteDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.NoteUpdateView.as_view(), name="update"),
    path("<int:pk>/status/<str:status>/", views.update_status, name="update-status"),
    path("attachments/<int:pk>/download/", views.NoteAttachmentDownloadView.as_view(), name="attachment-download"),
    path("<int:pk>/attachments/<int:attachment_pk>/delete/", views.delete_attachment, name="attachment-delete"),
    path("<int:pk>/archive/", views.toggle_archive, name="toggle-archive"),
    path("<int:pk>/create-client/", views.CreateClientFromNoteView.as_view(), name="create-client"),
    path("<int:pk>/create-project/", views.CreateProjectFromNoteView.as_view(), name="create-project"),
]
