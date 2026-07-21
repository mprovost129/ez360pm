from django.contrib import admin

from .models import Project, ProjectNumberSequence


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

