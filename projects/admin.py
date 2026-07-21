from django.contrib import admin

from .models import Project, ProjectNumberSequence, TimeEntry


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "client", "company", "status", "billing_type")
    list_filter = ("company", "status", "billing_type")
    search_fields = ("number", "name", "client__company_name", "address_1")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProjectNumberSequence)
class ProjectNumberSequenceAdmin(admin.ModelAdmin):
    list_display = ("company", "period", "last_value")
    list_filter = ("company", "period")


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "user",
        "start_time",
        "end_time",
        "duration_hours",
        "billable",
        "status",
    )
    list_filter = ("company", "status", "billable")
    search_fields = ("project__number", "project__name", "description", "user__email")
