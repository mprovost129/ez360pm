from django.contrib import admin

from .models import Client, Contact


class ContactInline(admin.TabularInline):
    model = Contact
    extra = 0
    min_num = 1


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("display_name", "company", "created_at")
    list_filter = ("company",)
    search_fields = ("company_name", "contacts__first_name", "contacts__last_name")
    inlines = (ContactInline,)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("get_full_name", "client", "email", "phone", "is_primary")
    list_filter = ("is_primary", "client__company")
    search_fields = ("first_name", "last_name", "email", "client__company_name")

