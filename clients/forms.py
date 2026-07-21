from django import forms
from django.db import transaction

from core.forms import CompanyScopedModelForm

from .models import Client, Contact
from .services import create_client_with_primary_contact, save_contact

CLIENT_FIELDS = (
    "company_name",
    "billing_address_1",
    "billing_address_2",
    "billing_city",
    "billing_state",
    "billing_postal_code",
    "billing_country",
    "internal_note",
)


class ClientForm(CompanyScopedModelForm):
    class Meta:
        model = Client
        fields = CLIENT_FIELDS
        widgets = {"internal_note": forms.Textarea(attrs={"rows": 3})}


class ClientCreateForm(ClientForm):
    contact_first_name = forms.CharField(max_length=150)
    contact_last_name = forms.CharField(max_length=150)
    contact_email = forms.EmailField()
    contact_phone = forms.CharField(max_length=50)

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("ClientCreateForm must be saved with commit=True.")
        client_data = {field: self.cleaned_data[field] for field in CLIENT_FIELDS}
        contact_data = {
            "first_name": self.cleaned_data["contact_first_name"],
            "last_name": self.cleaned_data["contact_last_name"],
            "email": self.cleaned_data["contact_email"],
            "phone": self.cleaned_data["contact_phone"],
        }
        self.instance = create_client_with_primary_contact(
            company=self.company,
            client_data=client_data,
            contact_data=contact_data,
        )
        return self.instance


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ("first_name", "last_name", "email", "phone", "is_primary")

    def __init__(self, *args, client, **kwargs):
        self.client = client
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        if not commit:
            raise ValueError("ContactForm must be saved with commit=True.")
        data = {field: self.cleaned_data[field] for field in self.Meta.fields}
        self.instance = save_contact(
            client=self.client,
            contact=self.instance if self.instance.pk else None,
            contact_data=data,
        )
        return self.instance

