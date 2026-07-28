from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Client, Contact

CLIENT_EDITABLE_FIELDS = {
    "company_name",
    "billing_address_1",
    "billing_address_2",
    "billing_city",
    "billing_state",
    "billing_postal_code",
    "billing_country",
    "internal_note",
}
CONTACT_EDITABLE_FIELDS = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "is_primary",
}


def _validated_fields(data, allowed, label):
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"Unsupported {label} fields: {', '.join(sorted(unknown))}.")
    return dict(data)


@transaction.atomic
def create_client_with_primary_contact(*, company, client_data, contact_data):
    client_data = _validated_fields(client_data, CLIENT_EDITABLE_FIELDS, "client")
    contact_data = _validated_fields(
        contact_data,
        CONTACT_EDITABLE_FIELDS - {"is_primary"},
        "contact",
    )
    client = Client(company=company, **client_data)
    client.full_clean()
    client.save()

    contact = Contact(client=client, is_primary=True, **contact_data)
    contact.full_clean()
    contact.save()
    return client


@transaction.atomic
def update_client(*, client, client_data):
    data = _validated_fields(client_data, CLIENT_EDITABLE_FIELDS, "client")
    locked = Client.objects.select_for_update().get(pk=client.pk)
    for field, value in data.items():
        setattr(locked, field, value)
    locked.full_clean()
    locked.save(update_fields=[*data.keys()])
    return locked


@transaction.atomic
def save_contact(*, client, contact_data, contact=None):
    data = _validated_fields(contact_data, CONTACT_EDITABLE_FIELDS, "contact")
    contacts = Contact.objects.select_for_update().filter(client=client)
    if contact is None:
        contact = Contact(client=client)
    else:
        contact = contacts.filter(pk=contact.pk).first()
        if contact is None:
            raise ValidationError("Contact does not belong to this client.")

    requested_primary = data.pop("is_primary", False)
    has_other_primary = contacts.exclude(pk=contact.pk).filter(is_primary=True).exists()
    contact.is_primary = requested_primary or not has_other_primary
    for field, value in data.items():
        setattr(contact, field, value)

    if contact.is_primary:
        contacts.exclude(pk=contact.pk).update(is_primary=False)
    contact.full_clean()
    contact.save()
    return contact


@transaction.atomic
def set_primary_contact(*, client, contact):
    locked_contact = (
        Contact.objects.select_for_update()
        .filter(client=client, pk=contact.pk)
        .first()
    )
    if locked_contact is None:
        raise ValidationError("Contact does not belong to this client.")
    Contact.objects.filter(client=client, is_primary=True).exclude(
        pk=locked_contact.pk
    ).update(is_primary=False)
    if not locked_contact.is_primary:
        locked_contact.is_primary = True
        locked_contact.full_clean()
        locked_contact.save(update_fields=["is_primary"])
    return locked_contact


@transaction.atomic
def delete_contact(*, contact):
    locked = Contact.objects.select_for_update().get(pk=contact.pk)
    if locked.is_primary:
        raise ValidationError(
            "Choose another primary contact before deleting this contact."
        )
    locked.delete()
