from django import forms
from django.conf import settings
from django.utils import timezone

from .models import AICompanySettings
from .policies import PRIVACY_NOTICE_VERSION, allowed_models


class AICompanySettingsForm(forms.ModelForm):
    acknowledge_privacy_notice = forms.BooleanField(
        required=False,
        label="I understand how EZ360PM sends data to the OpenAI API",
        help_text=(
            "The assistant sends the current command and only the company-scoped records "
            "needed to answer it. Full prompts and responses are not stored by EZ360PM."
        ),
    )

    class Meta:
        model = AICompanySettings
        fields = (
            "enabled",
            "access_mode",
            "model_override",
            "allow_low_risk_writes",
            "allow_structured_writes",
            "allow_financial_drafts",
            "allow_external_commits",
            "proactive_insights_enabled",
            "monthly_cost_limit_usd",
            "monthly_request_limit",
            "interaction_retention_days",
            "retain_interaction_summaries",
            "auto_pause_on_failures",
            "failure_threshold",
            "failure_window_minutes",
        )
        labels = {
            "enabled": "Enable the AI assistant for this company",
            "access_mode": "Who can use the AI assistant",
            "model_override": "OpenAI model",
            "allow_low_risk_writes": "Allow notes and timer actions",
            "allow_structured_writes": "Allow client and project changes",
            "allow_financial_drafts": "Allow proposal and invoice drafts",
            "allow_external_commits": "Allow confirmed sending and financial lifecycle actions",
            "proactive_insights_enabled": "Show proactive workflow alerts",
            "monthly_cost_limit_usd": "Monthly estimated API cost limit",
            "monthly_request_limit": "Monthly request limit",
            "interaction_retention_days": "Read-only interaction retention (days)",
            "retain_interaction_summaries": "Retain redacted interaction summaries",
            "auto_pause_on_failures": "Automatically pause AI after repeated failures",
            "failure_threshold": "Failures before automatic pause",
            "failure_window_minutes": "Failure-counting window (minutes)",
        }
        help_texts = {
            "model_override": "Choose from the models allowed by the deployment. Leave blank to use the platform default.",
            "allow_external_commits": "Every send, void, manual payment, and similar action still requires the exact final confirmation card.",
            "monthly_cost_limit_usd": "The lower of this value and the platform-wide hard limit is enforced.",
            "monthly_request_limit": "All successful and failed assistant requests count toward this company allowance.",
            "interaction_retention_days": "Write-action audit records are retained separately and are not deleted by the read-only history cleanup.",
            "retain_interaction_summaries": "Summaries are redacted and length-limited. Disable this to store only operational metadata.",
            "access_mode": "Use Selected users during a controlled pilot. Staff-only uses the Django staff flag.",
            "auto_pause_on_failures": "The rest of EZ360PM remains available if the assistant is paused.",
            "failure_threshold": "Counts failed assistant requests and failed confirmed actions, not canceled confirmations.",
            "failure_window_minutes": "The circuit breaker pauses AI when the threshold is reached inside this rolling window.",
        }
        widgets = {
            "monthly_cost_limit_usd": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "monthly_request_limit": forms.NumberInput(attrs={"min": "1"}),
            "interaction_retention_days": forms.NumberInput(attrs={"min": "7", "max": "2555"}),
            "failure_threshold": forms.NumberInput(attrs={"min": "2", "max": "100"}),
            "failure_window_minutes": forms.NumberInput(attrs={"min": "5", "max": "1440"}),
        }

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if kwargs.get("data") is not None and instance is not None:
            data = kwargs["data"].copy()
            for field_name in (
                "access_mode",
                "failure_threshold",
                "failure_window_minutes",
            ):
                if field_name not in data:
                    data[field_name] = getattr(instance, field_name)
            kwargs["data"] = data
        super().__init__(*args, **kwargs)
        choices = [("", f"Platform default ({settings.AI_MODEL})")]
        choices.extend((model, model) for model in allowed_models())
        self.fields["model_override"] = forms.ChoiceField(
            choices=choices,
            required=False,
            label=self._meta.labels["model_override"],
            help_text=self._meta.help_texts["model_override"],
        )
        acknowledged = bool(
            self.instance
            and self.instance.pk
            and self.instance.privacy_notice_acknowledged_at
        )
        self.fields["acknowledge_privacy_notice"].initial = acknowledged

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        acknowledged = cleaned.get("acknowledge_privacy_notice")
        if enabled and not acknowledged:
            self.add_error(
                "acknowledge_privacy_notice",
                "Review and acknowledge the AI data-processing notice before enabling the assistant.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        acknowledged = self.cleaned_data.get("acknowledge_privacy_notice")
        if acknowledged:
            if not instance.privacy_notice_acknowledged_at:
                instance.privacy_notice_acknowledged_at = timezone.now()
            instance.privacy_notice_version = PRIVACY_NOTICE_VERSION
        elif not instance.enabled:
            instance.privacy_notice_acknowledged_at = None
            instance.privacy_notice_version = ""
        if commit:
            instance.save()
        return instance
