import io
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Company, User


class BootstrapPersonalCommandTests(TestCase):
    password = "Strong-Bootstrap-Password-483!"

    def run_command(self, **overrides):
        options = {
            "company_name": "Provost Home Design",
            "email": "owner@example.com",
            "first_name": "Michael",
            "last_name": "Provost",
            "password_env": "TEST_EZ360PM_OWNER_PASSWORD",
            "no_input": True,
            "stdout": io.StringIO(),
        }
        options.update(overrides)
        with patch.dict(
            "os.environ",
            {"TEST_EZ360PM_OWNER_PASSWORD": self.password},
        ):
            call_command("bootstrap_personal", **options)
        return options["stdout"].getvalue()

    def test_command_creates_company_and_owner(self):
        output = self.run_command()

        company = Company.objects.get()
        user = User.objects.get()
        self.assertEqual(company.name, "Provost Home Design")
        self.assertEqual(company.email, "owner@example.com")
        self.assertEqual(user.company, company)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(self.password))
        self.assertIn("Created owner", output)

    def test_command_is_idempotent(self):
        self.run_command()
        output = self.run_command(company_name="Provost Home Design LLC")

        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Company.objects.get().name, "Provost Home Design LLC")
        self.assertIn("Updated owner", output)

    def test_no_input_requires_password_for_new_owner(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesMessage(CommandError, "Set MISSING_PASSWORD"):
                call_command(
                    "bootstrap_personal",
                    company_name="Provost Home Design",
                    email="owner@example.com",
                    password_env="MISSING_PASSWORD",
                    no_input=True,
                )
