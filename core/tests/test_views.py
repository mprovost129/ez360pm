from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User


class HealthViewTests(TestCase):
    def test_health_check_includes_database(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_check_fails_when_cache_is_unavailable(self):
        with patch("core.views.cache.set", side_effect=ConnectionError):
            response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


class DashboardViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
            first_name="Michael",
            last_name="Provost",
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
        self.assertContains(response, "Open intake")
        self.assertContains(response, "Lead projects")

    def test_dashboard_shell_uses_product_brand_assets(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "images/ez360pm_logo.svg")
        self.assertContains(response, "images/EZ360PM_icon_transparent_128.png")
        self.assertContains(response, "images/favicon.ico")
        self.assertContains(response, "site.webmanifest")

    def test_header_branding_shows_only_company_logo_when_configured(self):
        self.company.logo.name = "company_logos/company-logo.png"
        self.company.save(update_fields=["logo"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'class="company-logo"')
        self.assertContains(response, 'alt="Provost Home Design logo"')
        self.assertNotContains(
            response,
            '<span class="company-name">Provost Home Design</span>',
            html=True,
        )

    def test_header_branding_falls_back_to_company_name(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(
            response,
            '<span class="company-name">Provost Home Design</span>',
            html=True,
        )
        self.assertNotContains(response, 'class="company-logo"')

    def test_header_branding_falls_back_to_user_full_name(self):
        self.company.name = ""
        self.company.save(update_fields=["name"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(
            response,
            '<span class="company-name">Michael Provost</span>',
            html=True,
        )
        self.assertNotContains(response, 'class="company-logo"')

    def test_logout_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)


class DeploymentCheckCommandTests(TestCase):
    def test_deployment_check_passes_with_current_migrations(self):
        call_command("deployment_check", skip_cache=True, verbosity=0)
