from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assistant"

    def ready(self):
        from . import (
            checks,  # noqa: F401
            signals,  # noqa: F401
        )
