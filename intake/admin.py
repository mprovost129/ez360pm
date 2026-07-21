from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("short_body", "company", "client", "project", "is_archived", "created_at")
    list_filter = ("company", "is_archived")
    search_fields = ("body", "client__company_name", "project__name")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Note")
    def short_body(self, obj):
        return str(obj)

