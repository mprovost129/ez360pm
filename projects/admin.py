from django.contrib import admin

from .models import (
    ClientFormQuestion,
    ClientFormTemplate,
    Project,
    ProjectClientForm,
    ProjectFormUpload,
    ProjectNumberSequence,
    TimeEntry,
)


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


class ClientFormQuestionInline(admin.TabularInline):
    model = ClientFormQuestion
    extra = 0
    ordering = ("order",)


@admin.register(ClientFormTemplate)
class ClientFormTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "is_active", "updated_at")
    list_filter = ("company", "is_active")
    inlines = (ClientFormQuestionInline,)


@admin.register(ProjectClientForm)
class ProjectClientFormAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "recipient_email", "status", "email_status")
    list_filter = ("company", "status", "email_status")
    search_fields = ("title", "project__number", "recipient_email")
    readonly_fields = (
        "public_token",
        "sent_at",
        "viewed_at",
        "saved_at",
        "submitted_at",
        "revoked_at",
        "submission_notified_at",
    )


@admin.register(ProjectFormUpload)
class ProjectFormUploadAdmin(admin.ModelAdmin):
    list_display = ("original_name", "question", "size", "uploaded_at")
    search_fields = ("original_name", "question__label", "question__project_form__project__number")
    readonly_fields = ("original_name", "content_type", "size", "uploaded_at")
