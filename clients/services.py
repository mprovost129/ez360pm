from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Client, Contact


@transaction.atomic
def create_client_with_primary_contact(*, company, client_data, contact_data):
    client = Client(company=company, **client_data)
    client.full_clean()
    client.save()

    contact = Contact(client=client, is_primary=True, **contact_data)
    contact.full_clean()
    contact.save()
    return client


@transaction.atomic
def save_contact(*, client, contact_data, contact=None):
    contacts = Contact.objects.select_for_update().filter(client=client)
    if contact is None:
        contact = Contact(client=client)
    elif contact.client_id != client.pk:
        raise ValidationError("Contact does not belong to this client.")

    requested_primary = contact_data.pop("is_primary", False)
    has_other_primary = contacts.exclude(pk=contact.pk).filter(is_primary=True).exists()
    contact.is_primary = requested_primary or not has_other_primary
    for field, value in contact_data.items():
        setattr(contact, field, value)

    if contact.is_primary:
        contacts.exclude(pk=contact.pk).update(is_primary=False)
    contact.full_clean()
    contact.save()
    return contact


@transaction.atomic
def delete_contact(*, contact):
    locked = Contact.objects.select_for_update().get(pk=contact.pk)
    if locked.is_primary:
        raise ValidationError(
            "Choose another primary contact before deleting this contact."
        )
    locked.delete()
