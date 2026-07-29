from django.urls import path

from . import client_form_views, time_views, views

app_name = "projects"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("new/", views.ProjectCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="delete"),
    path("<int:pk>/start-without-retainer/", views.project_start_without_retainer, name="start-without-retainer"),
    path("<int:pk>/complete/", views.project_complete, name="complete"),
    path("form-templates/", client_form_views.ClientFormTemplateListView.as_view(), name="form-template-list"),
    path("form-templates/new/", client_form_views.ClientFormTemplateCreateView.as_view(), name="form-template-create"),
    path("form-templates/<int:pk>/", client_form_views.ClientFormTemplateDetailView.as_view(), name="form-template-detail"),
    path("form-templates/<int:pk>/edit/", client_form_views.ClientFormTemplateUpdateView.as_view(), name="form-template-update"),
    path("form-templates/<int:template_pk>/questions/new/", client_form_views.ClientFormQuestionView.as_view(), name="form-question-create"),
    path("form-templates/<int:template_pk>/questions/<int:question_pk>/edit/", client_form_views.ClientFormQuestionView.as_view(), name="form-question-update"),
    path("form-templates/<int:template_pk>/questions/<int:question_pk>/delete/", client_form_views.ClientFormQuestionDeleteView.as_view(), name="form-question-delete"),
    path("form-templates/<int:template_pk>/questions/<int:question_pk>/move/<str:direction>/", client_form_views.ClientFormQuestionMoveView.as_view(), name="form-question-move"),
    path("<int:pk>/forms/new/", client_form_views.ProjectClientFormCreateView.as_view(), name="client-form-create"),
    path("<int:pk>/forms/<int:form_pk>/", client_form_views.ProjectClientFormDetailView.as_view(), name="client-form-detail"),
    path("<int:pk>/forms/<int:form_pk>/edit/", client_form_views.ProjectClientFormUpdateView.as_view(), name="client-form-update"),
    path("<int:pk>/forms/<int:form_pk>/resend/", client_form_views.ProjectClientFormResendView.as_view(), name="client-form-resend"),
    path("<int:pk>/specifications/", client_form_views.ProjectSpecificationsView.as_view(), name="specifications"),
    path("time/", time_views.TimeEntryListView.as_view(), name="time-list"),
    path("time/start/", time_views.TimerStartView.as_view(), name="timer-start"),
    path("time/stop/", time_views.timer_stop, name="timer-stop"),
    path("time/pause/", time_views.timer_pause, name="timer-pause"),
    path("time/resume/", time_views.timer_resume, name="timer-resume"),
    path("time/new/", time_views.TimeEntryCreateView.as_view(), name="time-create"),
    path("time/<int:pk>/edit/", time_views.TimeEntryUpdateView.as_view(), name="time-update"),
    path("time/<int:pk>/delete/", time_views.TimeEntryDeleteView.as_view(), name="time-delete"),
]
