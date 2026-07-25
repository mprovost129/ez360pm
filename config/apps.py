from django.apps import AppConfig


class JetConfig(AppConfig):
    """Keep django-jet-reboot aligned with its committed migrations."""

    name = "jet"
    default_auto_field = "django.db.models.AutoField"


class JetDashboardConfig(AppConfig):
    """Keep django-jet-reboot dashboard IDs as legacy AutoField values."""

    name = "jet.dashboard"
    default_auto_field = "django.db.models.AutoField"
