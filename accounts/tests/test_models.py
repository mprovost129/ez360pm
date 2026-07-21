from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from accounts.models import Company, CompanyOwnedModel, User


class CompanyModelTests(TestCase):
    def test_company_defaults_are_safe_for_initial_setup(self):
        company = Company.objects.create(name="Provost Home Design")

        self.assertEqual(str(company), "Provost Home Design")
        self.assertEqual(str(company.default_hourly_rate), "0.00")
        self.assertFalse(company.accept_payments_default)


class UserModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")

    def test_create_user_normalizes_email_and_requires_company(self):
        user = User.objects.create_user(
            "  OWNER@EXAMPLE.COM ",
            "Strong-Test-Password-483!",
            company=self.company,
        )

        self.assertEqual(user.email, "owner@example.com")
        self.assertTrue(user.check_password("Strong-Test-Password-483!"))
        self.assertEqual(user.company, self.company)

        with self.assertRaisesMessage(ValueError, "company is required"):
            User.objects.create_user("other@example.com", "password")

    def test_email_is_case_insensitively_unique(self):
        User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                "OWNER@example.com",
                "Strong-Test-Password-483!",
                company=self.company,
            )

    def test_company_is_protected_while_it_has_users(self):
        User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )

        with self.assertRaises(ProtectedError):
            self.company.delete()

    def test_user_queryset_can_be_scoped_to_company(self):
        other_company = Company.objects.create(name="Other Company")
        owner = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=other_company,
        )

        self.assertEqual(list(User.objects.for_company(self.company)), [owner])
        self.assertFalse(User.objects.for_company(None).exists())

    def test_company_owned_model_is_abstract(self):
        self.assertTrue(CompanyOwnedModel._meta.abstract)

