from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("ask/", views.ask, name="ask"),
    path("home-data/", views.assistant_home_data, name="home-data"),
    path("insights/dismiss/", views.dismiss_proactive_insight, name="dismiss-insight"),
    path("events/", views.record_client_event, name="record-event"),
    path("feedback/", views.submit_feedback, name="feedback"),
    path("incidents/report/", views.report_incident, name="report-incident"),
    path("pilot/", views.pilot_operations, name="pilot-operations"),
    path("pilot/users/access/", views.update_pilot_user_access, name="pilot-user-access"),
    path("pilot/suspend/", views.suspend_ai, name="pilot-suspend"),
    path("pilot/resume/", views.resume_ai, name="pilot-resume"),
    path("pilot/incidents/<int:incident_id>/resolve/", views.resolve_incident, name="resolve-incident"),
    path("actions/", views.action_center, name="action-center"),
    path("usage/", views.usage, name="usage"),
    path("draft-quality/", views.draft_quality, name="draft-quality"),
    path("draft-quality/export.csv", views.draft_quality_export, name="draft-quality-export"),
    path("follow-up-evidence/", views.follow_up_evidence, name="follow-up-evidence"),
    path("follow-up-evidence/export.csv", views.follow_up_evidence_export, name="follow-up-evidence-export"),
    path("readiness/", views.readiness, name="readiness"),
    path("readiness/test-connection/", views.connection_test, name="connection-test"),
    path("evaluations/", views.evaluations, name="evaluations"),
    path("usage/export.csv", views.usage_export, name="usage-export"),
    path("settings/", views.AICompanySettingsView.as_view(), name="settings"),
    path("actions/<uuid:token>/confirm/", views.confirm_action, name="confirm-action"),
    path("actions/<uuid:token>/cancel/", views.cancel_action, name="cancel-action"),
]
