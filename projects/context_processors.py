from django.utils import timezone

from .models import TimeEntry


def _format_elapsed(total_seconds):
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def running_timer(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {}
    entry = (
        TimeEntry.objects.for_company(user.company)
        .filter(user=user, end_time__isnull=True)
        .select_related("project")
        .first()
    )
    context = {"running_time_entry": entry}
    if entry is not None:
        server_now = timezone.now()
        context.update(
            running_timer_start_ms=int(entry.start_time.timestamp() * 1000),
            running_timer_server_now_ms=int(server_now.timestamp() * 1000),
            running_timer_elapsed=_format_elapsed(
                (server_now - entry.start_time).total_seconds()
            ),
        )
    return context
