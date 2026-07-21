from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User
from clients.models import Client
from clients.services import (
    create_client_with_primary_contact,
    delete_contact,
    save_contact,
)


def create_client(company, *, company_name="Provost Client", last_name="Smith"):
    return create_client_with_primary_contact(
        company=company,
        client_data={"company_name": company_name},
        contact_data={
            "first_name": "Alex",
            "last_name": last_name,
            "email": f"{last_name.lower()}@example.com",
            "phone": "555-0100",
        },
    )


class ClientServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.client = create_client(self.company)

    def test_client_creation_always_has_one_primary_contact(self):
        self.assertEqual(self.client.contacts.count(), 1)
        self.assertTrue(self.client.primary_contact.is_primary)

    def test_promoting_contact_demotes_previous_primary(self):
        second = save_contact(
            client=self.client,
            contact_data={
                "first_name": "Blair",
                "last_name": "Jones",
                "email": "blair@example.com",
                "phone": "555-0101",
                "is_primary": False,
            },
        )
        self.assertFalse(second.is_primary)

        second = save_contact(
            client=self.client,
            contact=second,
            contact_data={
                "first_name": "Blair",
                "last_name": "Jones",
                "email": "blair@example.com",
                "phone": "555-0101",
                "is_primary": True,
            },
        )

        self.assertTrue(second.is_primary)
        self.assertEqual(self.client.contacts.filter(is_primary=True).count(), 1)
        self.assertEqual(self.client.primary_contact.pk, second.pk)

    def test_primary_contact_cannot_be_deleted(self):
        with self.assertRaises(ValidationError):
            delete_contact(contact=self.client.primary_contact)

    def test_list_order_falls_back_to_primary_last_name(self):
        individual = create_client(self.company, company_name="", last_name="Anders")

        ordered = list(Client.objects.for_company(self.company).ordered_for_list())

        self.assertEqual(ordered, [individual, self.client])


class ClientViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_create_client_and_primary_contact(self):
        response = self.client.post(
            reverse("clients:create"),
            {
                "company_name": "New Household",
                "billing_address_1": "10 Main Street",
                "billing_address_2": "",
                "billing_city": "Richmond",
                "billing_state": "VA",
                "billing_postal_code": "23220",
                "billing_country": "United States",
                "internal_note": "Referred by Pat.",
                "contact_first_name": "Jamie",
                "contact_last_name": "Taylor",
                "contact_email": "jamie@example.com",
                "contact_phone": "555-0102",
            },
        )

        created = Client.objects.get(company=self.company)
        self.assertRedirects(response, reverse("clients:detail", args=(created.pk,)))
        self.assertEqual(created.contacts.filter(is_primary=True).count(), 1)

    def test_other_company_client_is_not_retrievable(self):
        other_client = create_client(self.other_company, company_name="Hidden Client")

        response = self.client.get(reverse("clients:detail", args=(other_client.pk,)))

        self.assertEqual(response.status_code, 404)

