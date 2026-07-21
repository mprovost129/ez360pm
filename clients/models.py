from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Lower, NullIf

from accounts.managers import CompanyScopedManager, CompanyScopedQuerySet
from accounts.models import CompanyOwnedModel


class ClientQuerySet(CompanyScopedQuerySet):
    def ordered_for_list(self):
        primary_last_name = Contact.objects.filter(
            client=OuterRef("pk"),
            is_primary=True,
        ).values("last_name")[:1]
        return self.annotate(
            sort_name=Lower(
                Coalesce(
                    NullIf("company_name", Value("")),
                    Subquery(primary_last_name),
                    Value(""),
                )
            )
        ).order_by("sort_name", "pk")


class ClientManager(CompanyScopedManager.from_queryset(ClientQuerySet)):
    pass


class Client(CompanyOwnedModel):
    company_name = models.CharField(max_length=255, blank=True)
    billing_address_1 = models.CharField(max_length=255, blank=True)
    billing_address_2 = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(
        max_length=100,
        blank=True,
        default="United States",
    )
    internal_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ClientManager()

    class Meta:
        ordering = ("company_name", "pk")
        indexes = [models.Index(fields=("company", "company_name"))]

    @property
    def primary_contact(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("contacts")
        if prefetched is not None:
            return next((contact for contact in prefetched if contact.is_primary), None)
        return self.contacts.filter(is_primary=True).first()

    @property
    def display_name(self):
        if self.company_name:
            return self.company_name
        contact = self.primary_contact
        return contact.get_full_name() if contact else "Unnamed client"

    def __str__(self):
        return self.display_name


class Contact(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=50)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_primary", "last_name", "first_name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("client",),
                condition=models.Q(is_primary=True),
                name="clients_one_primary_contact",
            )
        ]

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.get_full_name()

