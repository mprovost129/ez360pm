from django.urls import path

from . import views
from .feature_gate import assistant_feature_required

app_name = "assistant"


def gated(view):
    return assistant_feature_required(view)


urlpatterns = [
    path("ask/", gated(views.ask), name="ask"),
    path("home-data/", gated(views.assistant_home_data), name="home-data"),
    path("insights/dismiss/", gated(views.dismiss_proactive_insight), name="dismiss-insight"),
    path("events/", gated(views.record_client_event), name="record-event"),
    path("feedback/", gated(views.submit_feedback), name="feedback"),
    path("incidents/report/", gated(views.report_incident), name="report-incident"),
    path("pilot/", gated(views.pilot_operations), name="pilot-operations"),
    path("pilot/users/access/", gated(views.update_pilot_user_access), name="pilot-user-access"),
    path("pilot/suspend/", gated(views.suspend_ai), name="pilot-suspend"),
    path("pilot/resume/", gated(views.resume_ai), name="pilot-resume"),
    path(
        "pilot/incidents/<int:incident_id>/resolve/",
        gated(views.resolve_incident),
        name="resolve-incident",
    ),
    path("actions/", gated(views.action_center), name="action-center"),
    path("usage/", gated(views.usage), name="usage"),
    path("draft-quality/", gated(views.draft_quality), name="draft-quality"),
    path(
        "draft-quality/export.csv",
        gated(views.draft_quality_export),
        name="draft-quality-export",
    ),
    path("follow-up-evidence/", gated(views.follow_up_evidence), name="follow-up-evidence"),
    path(
        "follow-up-evidence/export.csv",
        gated(views.follow_up_evidence_export),
        name="follow-up-evidence-export",
    ),
    path("readiness/", gated(views.readiness), name="readiness"),
    path(
        "readiness/test-connection/",
        gated(views.connection_test),
        name="connection-test",
    ),
    path("evaluations/", gated(views.evaluations), name="evaluations"),
    path("usage/export.csv", gated(views.usage_export), name="usage-export"),
    path(
        "settings/",
        gated(views.AICompanySettingsView.as_view()),
        name="settings",
    ),
    path(
        "actions/<uuid:token>/confirm/",
        gated(views.confirm_action),
        name="confirm-action",
    ),
    path(
        "actions/<uuid:token>/cancel/",
        gated(views.cancel_action),
        name="cancel-action",
    ),
]
