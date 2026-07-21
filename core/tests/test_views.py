from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User


class HealthViewTests(TestCase):
    def test_health_check_includes_database(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class DashboardViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
            first_name="Michael",
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("core:home"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('core:home')}",
        )

    def test_dashboard_uses_authenticated_company(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Provost Home Design")
        self.assertContains(response, "Your workspace is ready")

    def test_logout_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)


class DeploymentCheckCommandTests(TestCase):
    def test_deployment_check_passes_with_current_migrations(self):
        call_command("deployment_check", skip_cache=True, verbosity=0)

