from django.contrib import admin

from .models import ActivityEvent, ActivityItem, Note, NoteAttachment


class NoteAttachmentInline(admin.TabularInline):
    model = NoteAttachment
    extra = 0
    readonly_fields = ("original_name", "content_type", "size", "uploaded_by", "created_at")


class ActivityItemInline(admin.TabularInline):
    model = ActivityItem
    extra = 0
    ordering = ("order", "pk")


class ActivityEventInline(admin.TabularInline):
    model = ActivityEvent
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "actor", "description", "metadata", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = (
        "short_body",
        "contact_name",
        "prospect_company_name",
        "company",
        "client",
        "project",
        "activity_type",
        "status",
        "is_archived",
        "created_at",
    )
    list_filter = ("company", "activity_type", "source_type", "status", "is_archived")
    search_fields = (
        "body",
        "contact_first_name",
        "contact_last_name",
        "prospect_company_name",
        "client__company_name",
        "project__name",
    )
    readonly_fields = ("created_at", "updated_at", "resolved_at")
    inlines = (ActivityItemInline, NoteAttachmentInline, ActivityEventInline)

    @admin.display(description="Note")
    def short_body(self, obj):
        return str(obj)

    @admin.display(description="Contact")
    def contact_name(self, obj):
        return f"{obj.contact_first_name} {obj.contact_last_name}".strip()
