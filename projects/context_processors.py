from .models import TimeEntry


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
    return {"running_time_entry": entry}
