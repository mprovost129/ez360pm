from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="EZ360PM <noreply@example.com>",
)
class AccountAccessTests(TestCase):
    password = "Strong-Test-Password-483!"

    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            self.password,
            company=self.company,
        )

    def test_login_normalizes_email_capitalization_and_whitespace(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "  OWNER@EXAMPLE.COM ", "password": self.password},
        )

        self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_password_reset_sends_namespaced_recovery_link(self):
        response = self.client.post(
            reverse("accounts:password-reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("accounts:password-reset-done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_authenticated_owner_can_open_password_change(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:password-change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change password")

    def test_staff_without_superuser_cannot_open_administration(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_open_administration(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
