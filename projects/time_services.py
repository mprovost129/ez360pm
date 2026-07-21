from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User

from .models import Project, TimeEntry


class TimerAlreadyRunning(ValidationError):
    def __init__(self, entry):
        self.entry = entry
        super().__init__(f"A timer is already running for {entry.project}.")


@transaction.atomic
def start_timer(*, user, project, description="", billable=True, at=None):
    locked_user = User.objects.select_for_update().get(pk=user.pk)
    try:
        project = Project.objects.for_company(locked_user.company).get(pk=project.pk)
    except Project.DoesNotExist:
        raise ValidationError("Project must belong to the user's company.") from None
    if not project.accepts_time:
        raise ValidationError("Time cannot be started for this project status.")

    running = (
        TimeEntry.objects.select_related("project")
        .filter(user=locked_user, end_time__isnull=True)
        .first()
    )
    if running:
        raise TimerAlreadyRunning(running)

    entry = TimeEntry(
        company=locked_user.company,
        project=project,
        user=locked_user,
        start_time=at or timezone.now(),
        description=description.strip(),
        billable=billable,
    )
    entry.full_clean()
    try:
        with transaction.atomic():
            entry.save()
    except IntegrityError:
        running = TimeEntry.objects.select_related("project").get(
            user=locked_user,
            end_time__isnull=True,
        )
        raise TimerAlreadyRunning(running) from None
    return entry


@transaction.atomic
def stop_timer(*, user, at=None):
    entry = (
        TimeEntry.objects.select_for_update()
        .select_related("project")
        .filter(user=user, company=user.company, end_time__isnull=True)
        .first()
    )
    if entry is None:
        raise ValidationError("No timer is currently running.")

    stopped_at = at or timezone.now()
    if stopped_at <= entry.start_time:
        raise ValidationError("Timer stop time must be after its start time.")
    entry.end_time = stopped_at
    entry.full_clean()
    entry.save(update_fields=["end_time"])
    return entry


@transaction.atomic
def save_manual_entry(*, user, project, entry_data, entry=None):
    try:
        project = Project.objects.for_company(user.company).get(pk=project.pk)
    except Project.DoesNotExist:
        raise ValidationError("Project must belong to the user's company.") from None
    if entry is None:
        entry = TimeEntry(company=user.company, project=project, user=user)
    else:
        entry = TimeEntry.objects.select_for_update().get(
            pk=entry.pk,
            company=user.company,
            user=user,
        )
        if entry.status == TimeEntry.Status.INVOICED:
            raise ValidationError("Invoiced time cannot be edited.")
        if entry.is_running:
            raise ValidationError("Stop the timer before editing this entry.")
        entry.project = project

    for field, value in entry_data.items():
        setattr(entry, field, value)
    entry.user = user
    entry.company = user.company
    entry.status = TimeEntry.Status.LOGGED
    entry.full_clean()
    entry.save()
    return entry
