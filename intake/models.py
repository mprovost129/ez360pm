from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import CompanyOwnedModel
from clients.models import Client
from projects.models import Project


class Note(CompanyOwnedModel):
    contact_first_name = models.CharField(max_length=150, blank=True)
    contact_last_name = models.CharField(max_length=150, blank=True)
    prospect_company_name = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="notes",
        blank=True,
        null=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="notes",
        blank=True,
        null=True,
    )
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_archived", "-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "is_archived", "-created_at")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.client_id and self.client.company_id != self.company_id:
            errors["client"] = "Client must belong to the same company."
        if self.project_id:
            if self.project.company_id != self.company_id:
                errors["project"] = "Project must belong to the same company."
            elif self.client_id and self.client_id != self.project.client_id:
                errors["client"] = "The selected client does not own this project."
            else:
                self.client = self.project.client
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.body[:80]
