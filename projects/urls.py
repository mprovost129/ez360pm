from django.urls import path

from . import time_views, views

app_name = "projects"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("new/", views.ProjectCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="delete"),
    path("<int:pk>/start-without-retainer/", views.project_start_without_retainer, name="start-without-retainer"),
    path("<int:pk>/complete/", views.project_complete, name="complete"),
    path("time/", time_views.TimeEntryListView.as_view(), name="time-list"),
    path("time/start/", time_views.TimerStartView.as_view(), name="timer-start"),
    path("time/stop/", time_views.timer_stop, name="timer-stop"),
    path("time/new/", time_views.TimeEntryCreateView.as_view(), name="time-create"),
    path("time/<int:pk>/edit/", time_views.TimeEntryUpdateView.as_view(), name="time-update"),
    path("time/<int:pk>/delete/", time_views.TimeEntryDeleteView.as_view(), name="time-delete"),
]
