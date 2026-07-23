from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from core.forms import CompanyScopedModelForm

from .models import Project, TimeEntry
from .time_services import save_manual_entry


def trackable_projects(company):
    return Project.objects.for_company(company).filter(
        status__in=(
            Project.Status.LEAD,
            Project.Status.APPROVED,
            Project.Status.ACTIVE,
        )
    )


class TimerStartForm(forms.Form):
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    description = forms.CharField(max_length=255, required=False)
    billable = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["project"].queryset = trackable_projects(company)


class TimeEntryForm(CompanyScopedModelForm):
    start_time = forms.SplitDateTimeField(
        widget=forms.SplitDateTimeWidget(
            date_attrs={"type": "date"},
            time_attrs={"type": "time", "step": 60},
        )
    )
    duration_hours = forms.IntegerField(min_value=0, label="Hours", initial=0)
    duration_minutes = forms.IntegerField(
        min_value=0, max_value=59, label="Minutes", initial=0
    )

    class Meta:
        model = TimeEntry
        fields = ("project", "start_time", "description", "billable")

    def __init__(self, *args, company=None, user, **kwargs):
        self.user = user
        super().__init__(*args, company=company, **kwargs)
        self.fields["project"].queryset = Project.objects.for_company(self.company)
        if self.instance.pk and self.instance.end_time:
            total_minutes = int(self.instance.duration.total_seconds() // 60)
            hours, minutes = divmod(total_minutes, 60)
            self.fields["duration_hours"].initial = hours
            self.fields["duration_minutes"].initial = minutes

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        hours = cleaned.get("duration_hours")
        minutes = cleaned.get("duration_minutes")
        if start and hours is not None and minutes is not None:
            if hours == 0 and minutes == 0:
                self.add_error(None, "Enter a duration greater than zero.")
            else:
                # Hours/minutes represent active work. Preserve any pause history
                # on a timer-created entry without subtracting it a second time.
                paused_duration = self.instance.paused_duration or timedelta()
                cleaned["end_time"] = (
                    start
                    + timedelta(hours=hours, minutes=minutes)
                    + paused_duration
                )
                conflict = (
                    TimeEntry.objects.filter(
                        company=self.company,
                        user=self.user,
                        start_time__lt=cleaned["end_time"],
                    )
                    .exclude(pk=self.instance.pk)
                    .filter(Q(end_time__gt=start) | Q(end_time__isnull=True))
                    .select_related("project")
                    .first()
                )
                if conflict:
                    conflict_start = timezone.localtime(conflict.start_time).strftime(
                        "%b %d, %Y at %I:%M %p"
                    )
                    self.add_error(
                        None,
                        "This time overlaps an existing entry for "
                        f"{conflict.project.number} starting {conflict_start}.",
                    )
        return cleaned

    def save(self, commit=True):
        if not commit:
            raise ValueError("TimeEntryForm must be saved with commit=True.")
        data = {
            field: self.cleaned_data[field]
            for field in ("start_time", "description", "billable")
        }
        data["end_time"] = self.cleaned_data["end_time"]
        self.instance = save_manual_entry(
            user=self.user,
            project=self.cleaned_data["project"],
            entry=self.instance if self.instance.pk else None,
            entry_data=data,
        )
        return self.instance


class TimeFilterForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label="All projects",
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    unbilled = forms.BooleanField(required=False, label="Unbilled billable time only")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.for_company(company)
